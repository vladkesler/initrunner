"""Agent builder routes -- seed, validate, and save new agents."""

from __future__ import annotations

import asyncio
import logging
import os
import re
from pathlib import Path
from typing import Annotated
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException

from initrunner.dashboard.deps import RoleCache, _role_id, get_role_cache
from initrunner.dashboard.schemas import (
    BuilderOptionsResponse,
    ModelOption,
    ProviderModels,
    ProviderPreset,
    SaveKeyRequest,
    SaveKeyResponse,
    SaveRequest,
    SaveResponse,
    SeedRequest,
    SeedResponse,
    TemplateInfo,
    ValidateRequest,
    ValidationIssueResponse,
)

_logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/builder", tags=["builder"])


# ---------------------------------------------------------------------------
# Constants & helpers
# ---------------------------------------------------------------------------

_BLANK_TEMPLATE = """\
apiVersion: initrunner/v1
kind: Agent
metadata:
  name: my-agent
  description: ""
spec:
  role: |
    You are a helpful assistant.
  model:
    provider: {provider}
    name: {model}
"""

_CUSTOM_PRESETS = [
    ProviderPreset(
        name="openrouter",
        label="OpenRouter",
        base_url="https://openrouter.ai/api/v1",
        api_key_env="OPENROUTER_API_KEY",
        placeholder="anthropic/claude-sonnet-4",
    ),
    ProviderPreset(
        name="custom",
        label="Custom endpoint",
        base_url="",
        api_key_env="",
        placeholder="model-name",
    ),
]

_CUSTOM_PROVIDER_NAMES = {p.name for p in _CUSTOM_PRESETS}


def _issues_to_response(issues: list) -> list[ValidationIssueResponse]:
    return [
        ValidationIssueResponse(field=i.field, message=i.message, severity=i.severity)
        for i in issues
    ]


def _inject_model_fields(yaml_text: str, **fields: str | None) -> str:
    """Insert key-value pairs into the spec.model section after the name: line."""
    lines = yaml_text.split("\n")
    result: list[str] = []
    in_model_block = False
    injected = False
    for line in lines:
        result.append(line)
        stripped = line.lstrip()
        # Enter model block at spec-level indentation (2+ spaces before "model:")
        if not in_model_block and stripped == "model:" and line.startswith("  model:"):
            in_model_block = True
        elif in_model_block and stripped.startswith("name:") and not injected:
            indent = " " * (len(line) - len(stripped))
            for k, v in fields.items():
                if v is not None:
                    result.append(f"{indent}{k}: {v}")
            injected = True
            in_model_block = False
    return "\n".join(result)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/templates")
async def builder_options(
    role_cache: Annotated[RoleCache, Depends(get_role_cache)],
) -> BuilderOptionsResponse:
    from initrunner.services.providers import OLLAMA_DEFAULT_BASE_URL
    from initrunner.templates import LISTABLE_TEMPLATES, PROVIDER_MODELS

    templates = [
        TemplateInfo(name=name, description=desc) for name, desc in LISTABLE_TEMPLATES.items()
    ]

    providers = [
        ProviderModels(
            provider=prov,
            models=[ModelOption(name=m, description=d) for m, d in models],
        )
        for prov, models in PROVIDER_MODELS.items()
    ]

    detected_provider: str | None = None
    detected_model: str | None = None
    try:
        from initrunner.services.providers import detect_provider_and_model

        detected = await asyncio.to_thread(detect_provider_and_model)
        if detected is not None:
            detected_provider = detected.provider
            detected_model = detected.model
    except Exception:
        _logger.debug("Provider detection failed", exc_info=True)

    # Ollama models -- query running instance
    ollama_models: list[str] = []
    try:
        from initrunner.services.providers import list_ollama_models

        ollama_models = await asyncio.to_thread(list_ollama_models)
    except Exception:
        _logger.debug("Ollama model detection failed", exc_info=True)

    from initrunner.config import get_roles_dir

    # Primary save dir is ~/.initrunner/roles (create if needed)
    save_dir = get_roles_dir()
    save_dir.mkdir(parents=True, exist_ok=True)
    role_dirs = [str(save_dir)]
    for d in role_cache._settings.extra_role_dirs:
        ds = str(d)
        if ds not in role_dirs:
            role_dirs.append(ds)

    # Check which preset keys are already configured
    presets = []
    for p in _CUSTOM_PRESETS:
        configured = bool(p.api_key_env and os.environ.get(p.api_key_env))
        presets.append(
            ProviderPreset(
                name=p.name,
                label=p.label,
                base_url=p.base_url,
                api_key_env=p.api_key_env,
                placeholder=p.placeholder,
                key_configured=configured,
            )
        )

    return BuilderOptionsResponse(
        templates=templates,
        providers=providers,
        detected_provider=detected_provider,
        detected_model=detected_model,
        role_dirs=role_dirs,
        custom_presets=presets,
        ollama_models=ollama_models,
        ollama_base_url=OLLAMA_DEFAULT_BASE_URL,
    )


@router.post("/seed")
async def seed_agent(
    req: SeedRequest,
) -> SeedResponse:
    from initrunner.services.agent_builder import BuilderSession

    # Normalize custom providers to openai for runtime
    is_custom = req.provider in _CUSTOM_PROVIDER_NAMES
    runtime_provider = "openai" if is_custom else req.provider

    # Resolve base_url/api_key_env from presets if not explicitly provided
    base_url = req.base_url
    api_key_env = req.api_key_env
    if is_custom and base_url is None:
        preset = next((p for p in _CUSTOM_PRESETS if p.name == req.provider), None)
        if preset and preset.base_url:
            base_url = preset.base_url
            api_key_env = api_key_env or preset.api_key_env

    # Validation
    if is_custom and req.provider == "custom" and not base_url:
        raise HTTPException(status_code=400, detail="base_url is required for custom endpoints")
    if is_custom and not req.model:
        raise HTTPException(
            status_code=400, detail="model name is required for custom/openrouter providers"
        )

    session = BuilderSession()

    def _run() -> tuple[str, str, list, bool]:
        if req.mode == "blank":
            from initrunner.templates import _default_model_name

            model = req.model or _default_model_name(runtime_provider)
            session.yaml_text = _BLANK_TEMPLATE.format(provider=runtime_provider, model=model)
            turn = session._make_turn_result("Minimal skeleton. Edit as needed.")
        elif req.mode == "template":
            if not req.template:
                raise ValueError("template field is required for mode=template")
            turn = session.seed_template(req.template, runtime_provider, req.model)
        elif req.mode == "description":
            if not req.description:
                raise ValueError("description field is required for mode=description")
            turn = session.seed_description(
                req.description,
                runtime_provider,
                req.model,
                base_url=base_url,
                api_key_env=api_key_env,
            )
        else:
            raise ValueError(f"Unknown mode: {req.mode}")
        return turn.explanation, turn.yaml_text, turn.issues, turn.ready

    try:
        explanation, yaml_text, issues, ready = await asyncio.to_thread(_run)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        _logger.error("Seed failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e)) from e

    # Inject base_url/api_key_env into the generated YAML
    if is_custom and base_url:
        yaml_text = _inject_model_fields(
            yaml_text,
            base_url=base_url,
            api_key_env=api_key_env if api_key_env else None,
        )
    elif req.provider == "ollama" and base_url:
        from initrunner.services.providers import OLLAMA_DEFAULT_BASE_URL

        if base_url != OLLAMA_DEFAULT_BASE_URL:
            yaml_text = _inject_model_fields(yaml_text, base_url=base_url)

    return SeedResponse(
        yaml_text=yaml_text,
        explanation=explanation,
        issues=_issues_to_response(issues),
        ready=ready,
    )


@router.post("/validate")
async def validate_yaml(req: ValidateRequest) -> SeedResponse:
    from initrunner.services.agent_builder import _validate_yaml

    _, issues = await asyncio.to_thread(_validate_yaml, req.yaml_text)
    ready = not any(i.severity == "error" for i in issues)

    return SeedResponse(
        yaml_text=req.yaml_text,
        explanation="",
        issues=_issues_to_response(issues),
        ready=ready,
    )


@router.post("/save")
async def save_agent(
    req: SaveRequest,
    role_cache: Annotated[RoleCache, Depends(get_role_cache)],
) -> SaveResponse:
    from initrunner.config import get_roles_dir
    from initrunner.services.agent_builder import BuilderSession

    # Validate directory is within discovered role dirs or ~/.initrunner/roles
    allowed_dirs = list(role_cache._settings.get_role_dirs())
    global_roles = get_roles_dir()
    if global_roles not in allowed_dirs:
        allowed_dirs.append(global_roles)
    target_dir = Path(req.directory).resolve()
    if not any(target_dir == d.resolve() for d in allowed_dirs):
        raise HTTPException(
            status_code=400,
            detail=f"Directory {req.directory} is not within a configured role directory. "
            f"Allowed: {[str(d) for d in allowed_dirs]}",
        )

    output_path = target_dir / req.filename
    session = BuilderSession()
    session.yaml_text = req.yaml_text

    def _run():
        return session.save(output_path, force=req.force)

    try:
        result = await asyncio.to_thread(_run)
    except FileExistsError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except (PermissionError, OSError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    # Refresh cache so the new agent appears immediately
    await asyncio.to_thread(role_cache.refresh)

    agent_id = _role_id(output_path)

    return SaveResponse(
        path=str(result.yaml_path),
        valid=result.valid,
        issues=result.issues,
        next_steps=result.next_steps,
        agent_id=agent_id,
    )


@router.post("/save-key")
async def save_key(req: SaveKeyRequest) -> SaveKeyResponse:
    from initrunner.config import get_global_env_path

    # Determine env var name
    if req.preset:
        preset = next((p for p in _CUSTOM_PRESETS if p.name == req.preset), None)
        if preset is None or not preset.api_key_env:
            raise HTTPException(status_code=400, detail=f"Unknown preset: {req.preset}")
        env_name = preset.api_key_env
    elif req.base_url:
        host = urlparse(req.base_url).hostname or "endpoint"
        sanitized = re.sub(r"[^A-Z0-9]", "_", host.upper()).strip("_")
        env_name = f"INITRUNNER_{sanitized}_KEY"
    else:
        raise HTTPException(status_code=400, detail="Either preset or base_url is required")

    # Write to ~/.initrunner/.env
    env_path = get_global_env_path()
    env_path.parent.mkdir(parents=True, exist_ok=True)

    def _write():
        existing = env_path.read_text() if env_path.exists() else ""
        lines = existing.splitlines()
        # Update existing or append
        updated = False
        for i, line in enumerate(lines):
            if line.startswith(f"{env_name}="):
                lines[i] = f"{env_name}={req.api_key}"
                updated = True
                break
        if not updated:
            lines.append(f"{env_name}={req.api_key}")
        env_path.write_text("\n".join(lines).strip() + "\n")

    await asyncio.to_thread(_write)

    # Set in current process so seed/run can use it immediately
    os.environ[env_name] = req.api_key

    return SaveKeyResponse(env_var=env_name)
