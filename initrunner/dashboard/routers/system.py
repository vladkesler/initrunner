"""System diagnostics and tool registry routes."""

from __future__ import annotations

import asyncio
import os

from fastapi import APIRouter  # type: ignore[import-not-found]

from initrunner.dashboard.schemas import (
    DefaultModelResponse,
    DoctorCheck,
    DoctorResponse,
    SaveDefaultModelRequest,
    ToolTypeResponse,
)

router = APIRouter(prefix="/api/system", tags=["system"])


def _run_doctor_checks() -> list[DoctorCheck]:
    """Run provider health checks (mirrors CLI doctor command)."""
    from initrunner.agent.loader import _PROVIDER_API_KEY_ENVS, _load_dotenv
    from initrunner.dashboard.routers._provider_options import CUSTOM_PRESETS

    _load_dotenv(None)

    checks: list[DoctorCheck] = []

    for provider, env_var in _PROVIDER_API_KEY_ENVS.items():
        key_set = bool(os.environ.get(env_var))
        if not key_set:
            checks.append(DoctorCheck(name=provider, status="fail", message="API key not set"))
            continue
        try:
            from initrunner._compat import require_provider

            require_provider(provider)
            checks.append(DoctorCheck(name=provider, status="ok", message="Ready"))
        except RuntimeError:
            checks.append(
                DoctorCheck(name=provider, status="warn", message="Key set but SDK missing")
            )

    # Custom presets (OpenRouter, etc.)
    for preset in CUSTOM_PRESETS:
        if not preset.api_key_env:
            continue
        key_set = bool(os.environ.get(preset.api_key_env))
        if key_set:
            checks.append(DoctorCheck(name=preset.name, status="ok", message="Ready"))
        else:
            checks.append(DoctorCheck(name=preset.name, status="fail", message="API key not set"))

    # Ollama
    try:
        from initrunner.services.providers import is_ollama_running

        if is_ollama_running():
            checks.append(DoctorCheck(name="ollama", status="ok", message="Running"))
        else:
            checks.append(DoctorCheck(name="ollama", status="fail", message="Not running"))
    except Exception:
        checks.append(DoctorCheck(name="ollama", status="fail", message="Not available"))

    # Docker
    try:
        from initrunner.agent.docker_sandbox import check_docker_available

        if check_docker_available():
            checks.append(DoctorCheck(name="docker", status="ok", message="Available"))
        else:
            checks.append(DoctorCheck(name="docker", status="fail", message="Not available"))
    except Exception:
        checks.append(DoctorCheck(name="docker", status="fail", message="Not available"))

    return checks


def _run_embedding_checks() -> list[DoctorCheck]:
    """Check embedding provider API key status."""
    from initrunner.agent.loader import _load_dotenv
    from initrunner.ingestion.embeddings import _PROVIDER_EMBEDDING_KEY_DEFAULTS

    _load_dotenv(None)

    checks: list[DoctorCheck] = []
    for provider, env_var in _PROVIDER_EMBEDDING_KEY_DEFAULTS.items():
        if os.environ.get(env_var):
            checks.append(DoctorCheck(name=provider, status="ok", message=f"{env_var} set"))
        else:
            checks.append(DoctorCheck(name=provider, status="fail", message=f"{env_var} not set"))

    # Ollama: no key needed
    try:
        from initrunner.services.providers import is_ollama_running

        if is_ollama_running():
            checks.append(DoctorCheck(name="ollama", status="ok", message="No key needed"))
        else:
            checks.append(DoctorCheck(name="ollama", status="fail", message="Not running"))
    except Exception:
        checks.append(DoctorCheck(name="ollama", status="fail", message="Not available"))

    return checks


def _list_tool_types() -> list[ToolTypeResponse]:
    """List all registered tool types with descriptions."""
    from initrunner.agent.tools._registry import get_tool_types

    types = get_tool_types()
    result = []
    for name, config_cls in sorted(types.items()):
        doc = config_cls.__doc__ or ""
        description = doc.strip().split("\n")[0] if doc.strip() else f"{name} tool"
        result.append(ToolTypeResponse(name=name, description=description))
    return result


@router.get("/doctor")
async def doctor() -> DoctorResponse:
    checks, embedding_checks = await asyncio.gather(
        asyncio.to_thread(_run_doctor_checks),
        asyncio.to_thread(_run_embedding_checks),
    )
    return DoctorResponse(checks=checks, embedding_checks=embedding_checks)


@router.get("/tools")
async def list_tools() -> list[ToolTypeResponse]:
    return await asyncio.to_thread(_list_tool_types)


# -- Default model -------------------------------------------------------------


def _get_default_model() -> DefaultModelResponse:
    from initrunner.agent.loader import detect_default_model

    prov, model, base_url, api_key_env, source = detect_default_model()
    return DefaultModelResponse(
        provider=prov,
        model=model,
        base_url=base_url,
        api_key_env=api_key_env,
        source=source,
    )


def _save_default_model(req: SaveDefaultModelRequest) -> DefaultModelResponse:
    from initrunner.cli.run_config import save_run_config
    from initrunner.dashboard.routers._provider_options import (
        CUSTOM_PROVIDER_NAMES,
        resolve_custom_provider,
    )

    # Normalize preset names to canonical runtime fields
    provider = req.provider
    base_url = req.base_url
    api_key_env = req.api_key_env
    if provider in CUSTOM_PROVIDER_NAMES:
        provider, base_url, api_key_env = resolve_custom_provider(provider, base_url, api_key_env)

    save_run_config(
        provider=provider,
        model=req.model,
        base_url=base_url,
        api_key_env=api_key_env,
    )
    return DefaultModelResponse(
        provider=provider,
        model=req.model,
        base_url=base_url,
        api_key_env=api_key_env,
        source="run_yaml",
    )


def _clear_default_model() -> DefaultModelResponse:
    from initrunner.cli.run_config import clear_run_config_model

    clear_run_config_model()
    return _get_default_model()


@router.get("/default-model")
async def get_default_model() -> DefaultModelResponse:
    return await asyncio.to_thread(_get_default_model)


@router.post("/default-model")
async def save_default_model(req: SaveDefaultModelRequest) -> DefaultModelResponse:
    return await asyncio.to_thread(_save_default_model, req)


@router.delete("/default-model")
async def reset_default_model() -> DefaultModelResponse:
    return await asyncio.to_thread(_clear_default_model)
