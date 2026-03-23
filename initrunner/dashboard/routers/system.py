"""System diagnostics and tool registry routes."""

from __future__ import annotations

import asyncio
import os

from fastapi import APIRouter

from initrunner.dashboard.schemas import DoctorCheck, DoctorResponse, ToolTypeResponse

router = APIRouter(prefix="/api/system", tags=["system"])


def _run_doctor_checks() -> list[DoctorCheck]:
    """Run provider health checks (mirrors CLI doctor command)."""
    from initrunner.agent.loader import _PROVIDER_API_KEY_ENVS, _load_dotenv

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
    checks = await asyncio.to_thread(_run_doctor_checks)
    return DoctorResponse(checks=checks)


@router.get("/tools")
async def list_tools() -> list[ToolTypeResponse]:
    return await asyncio.to_thread(_list_tool_types)
