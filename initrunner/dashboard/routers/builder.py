"""Agent builder routes -- seed, validate, and save new agents."""

from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from pathlib import Path
from typing import Annotated
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException

from initrunner.dashboard.deps import RoleCache, _role_id, get_role_cache
from initrunner.dashboard.routers._provider_options import (
    CUSTOM_PRESETS,
    CUSTOM_PROVIDER_NAMES,
    gather_provider_options,
    resolve_custom_provider,
)
from initrunner.dashboard.schemas import (
    BuilderOptionsResponse,
    EnvVarStatus,
    HubSearchResponse,
    HubSearchResultResponse,
    HubSeedRequest,
    SaveKeyRequest,
    SaveKeyResponse,
    SaveRequest,
    SaveResponse,
    SeedRequest,
    SeedResponse,
    TemplateInfo,
    TemplateSetup,
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


def _issues_to_response(issues: list) -> list[ValidationIssueResponse]:
    return [
        ValidationIssueResponse(field=i.field, message=i.message, severity=i.severity)
        for i in issues
    ]


def _rewrite_model_block(
    yaml_text: str,
    *,
    provider: str | None = None,
    name: str | None = None,
    base_url: str | None = None,
    api_key_env: str | None = None,
) -> str:
    """Replace or inject fields in the spec.model block.

    Scoped by indentation: enters the block when ``  model:`` is found
    (spec-level indent) and exits when indentation returns to that level
    or above.  ``provider:`` and ``name:`` lines are *replaced* in-place;
    ``base_url`` and ``api_key_env`` are *injected* after the ``name:`` line.
    """
    lines = yaml_text.split("\n")
    result: list[str] = []
    in_model = False
    model_indent = 0
    injected = False

    for line in lines:
        stripped = line.lstrip()

        # Detect entry into spec.model block
        if not in_model and stripped == "model:" and line.startswith("  model:"):
            in_model = True
            model_indent = len(line) - len(stripped)
            result.append(line)
            continue

        # Inside model block -- check if we've exited (indentation <= model key)
        if in_model and stripped and not stripped.startswith("#"):
            current_indent = len(line) - len(stripped)
            if current_indent <= model_indent:
                in_model = False

        if in_model:
            field_indent = " " * (len(line) - len(stripped))
            # Replace provider: line
            if provider is not None and stripped.startswith("provider:"):
                result.append(f"{field_indent}provider: {provider}")
                continue
            # Replace name: line, then inject trailing fields
            if stripped.startswith("name:"):
                if name is not None:
                    result.append(f"{field_indent}name: {name}")
                else:
                    result.append(line)
                if not injected:
                    if base_url is not None:
                        result.append(f"{field_indent}base_url: {base_url}")
                    if api_key_env is not None:
                        result.append(f"{field_indent}api_key_env: {api_key_env}")
                    injected = True
                continue

        result.append(line)

    return "\n".join(result)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/templates")
async def builder_options(
    role_cache: Annotated[RoleCache, Depends(get_role_cache)],
) -> BuilderOptionsResponse:
    from initrunner.templates import LISTABLE_TEMPLATES, TEMPLATE_SETUP

    opts = await gather_provider_options(role_cache._settings)

    templates = [
        TemplateInfo(name=name, description=desc) for name, desc in LISTABLE_TEMPLATES.items()
    ]

    template_setups: dict[str, TemplateSetup] = {}
    for tpl_name, setup in TEMPLATE_SETUP.items():
        template_setups[tpl_name] = TemplateSetup(
            steps=setup["steps"],
            env_vars=[
                EnvVarStatus(name=v, is_set=bool(os.environ.get(v))) for v in setup["env_vars"]
            ],
            extras=setup["extras"],
            docs_url=setup["docs_url"],
        )

    return BuilderOptionsResponse(
        templates=templates,
        providers=opts.providers,
        detected_provider=opts.detected_provider,
        detected_model=opts.detected_model,
        role_dirs=opts.save_dirs,
        custom_presets=opts.custom_presets,
        ollama_models=opts.ollama_models,
        ollama_base_url=opts.ollama_base_url,
        template_setups=template_setups,
    )


@router.post("/seed")
async def seed_agent(
    req: SeedRequest,
) -> SeedResponse:
    from initrunner.services.agent_builder import BuilderSession

    # Normalize custom providers to openai for runtime
    is_custom = req.provider in CUSTOM_PROVIDER_NAMES
    runtime_provider, base_url, api_key_env = resolve_custom_provider(
        req.provider, req.base_url, req.api_key_env
    )

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
        yaml_text = _rewrite_model_block(
            yaml_text,
            base_url=base_url,
            api_key_env=api_key_env if api_key_env else None,
        )
    elif req.provider == "ollama" and base_url:
        from initrunner.services.providers import OLLAMA_DEFAULT_BASE_URL

        if base_url != OLLAMA_DEFAULT_BASE_URL:
            yaml_text = _rewrite_model_block(yaml_text, base_url=base_url)

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
    if not any(target_dir.is_relative_to(d.resolve()) for d in allowed_dirs):
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
        preset = next((p for p in CUSTOM_PRESETS if p.name == req.preset), None)
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


# ---------------------------------------------------------------------------
# InitHub endpoints
# ---------------------------------------------------------------------------


@router.get("/hub-search")
async def hub_search_endpoint(
    q: str = "",
    tag: list[str] | None = None,
) -> HubSearchResponse:
    from initrunner.hub import HubError, hub_search

    if len(q) < 2:
        return HubSearchResponse(items=[])

    try:
        results = await asyncio.to_thread(hub_search, q, tags=tag)
    except HubError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e

    return HubSearchResponse(
        items=[
            HubSearchResultResponse(
                owner=r.owner,
                name=r.name,
                description=r.description,
                tags=r.tags,
                downloads=r.downloads,
                latest_version=r.latest_version,
            )
            for r in results
        ]
    )


# Featured packages cache (module-level, 5-min TTL)
_featured_cache: tuple[float, list[HubSearchResultResponse]] = (0.0, [])
_FEATURED_TTL = 300


@router.get("/hub-featured")
async def hub_featured_endpoint() -> HubSearchResponse:
    global _featured_cache

    from initrunner.hub import HubError, hub_browse

    now = time.monotonic()
    cached_at, cached_items = _featured_cache
    if cached_items and (now - cached_at) < _FEATURED_TTL:
        return HubSearchResponse(items=cached_items)

    try:
        results = await asyncio.to_thread(hub_browse, 12)
    except HubError:
        _logger.debug("hub_browse failed, returning cached/empty", exc_info=True)
        return HubSearchResponse(items=cached_items)

    items = [
        HubSearchResultResponse(
            owner=r.owner,
            name=r.name,
            description=r.description,
            tags=r.tags,
            downloads=r.downloads,
            latest_version=r.latest_version,
        )
        for r in results
    ]
    _featured_cache = (now, items)
    return HubSearchResponse(items=items)


@router.post("/hub-seed")
async def hub_seed_endpoint(req: HubSeedRequest) -> SeedResponse:
    import tarfile
    import tempfile

    from initrunner.hub import HubError, hub_download, parse_hub_source
    from initrunner.services.agent_builder import _validate_yaml

    # Parse ref into owner/name/version
    try:
        owner, name, version = parse_hub_source(req.ref)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    # Download bundle
    try:
        bundle_bytes = await asyncio.to_thread(hub_download, owner, name, version)
    except HubError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e

    # Extract to temp dir, read primary YAML, clean up immediately
    import io

    yaml_text = ""
    omitted: list[str] = []
    try:
        with tempfile.TemporaryDirectory(prefix="initrunner_hub_") as stage:
            stage_path = Path(stage)
            with tarfile.open(fileobj=io.BytesIO(bundle_bytes), mode="r:gz") as tar:
                tar.extractall(stage_path, filter="data")

            # Find primary YAML
            yamls = list(stage_path.glob("*.yaml")) + list(stage_path.glob("*.yml"))
            if not yamls:
                raise HTTPException(
                    status_code=400,
                    detail=f"No YAML files found in hub bundle '{req.ref}'",
                )
            primary = yamls[0]
            yaml_text = primary.read_text(encoding="utf-8")

            # Catalog sidecars
            for f in stage_path.rglob("*"):
                if f.is_file() and f != primary:
                    omitted.append(str(f.relative_to(stage_path)))
    except tarfile.TarError as e:
        raise HTTPException(status_code=400, detail=f"Invalid bundle archive: {e}") from e

    # Rewrite model block with user's provider/model choice
    is_custom = req.provider in CUSTOM_PROVIDER_NAMES
    runtime_provider = "openai" if is_custom else req.provider

    # Resolve base_url/api_key_env from presets
    base_url = req.base_url
    api_key_env = req.api_key_env
    if is_custom and base_url is None:
        preset = next((p for p in CUSTOM_PRESETS if p.name == req.provider), None)
        if preset and preset.base_url:
            base_url = preset.base_url
            api_key_env = api_key_env or preset.api_key_env

    yaml_text = _rewrite_model_block(
        yaml_text,
        provider=runtime_provider,
        name=req.model or None,
        base_url=base_url,
        api_key_env=api_key_env,
    )

    # Validate
    _, issues = await asyncio.to_thread(_validate_yaml, yaml_text)
    ready = not any(i.severity == "error" for i in issues)

    explanation = f"Loaded from InitHub: {owner}/{name}"
    if version:
        explanation += f"@{version}"
    if omitted:
        explanation += (
            f"\nNote: Bundle contains additional files not loaded: "
            f"{', '.join(omitted)}. Use 'initrunner install {owner}/{name}' "
            f"for the full package."
        )

    return SeedResponse(
        yaml_text=yaml_text,
        explanation=explanation,
        issues=_issues_to_response(issues),
        ready=ready,
    )
