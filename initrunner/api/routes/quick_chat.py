"""Quick Chat + Sense routes — provider-detected ephemeral chat."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse

from initrunner._ids import generate_id
from initrunner.api._helpers import run_in_thread
from initrunner.api._streaming import (
    build_sse_stream,
    error_stream_response,
    resolve_attachments,
    stage_upload,
)
from initrunner.api.authz import AuthzGuard, requires
from initrunner.api.state import role_path_to_id, sessions
from initrunner.authz import AGENT, EXECUTE, READ

router = APIRouter(tags=["quick-chat"])
_logger = logging.getLogger(__name__)

_QUICK_CHAT_ROLE_ID = "__quick_chat__"


def _templates(request: Request):
    return request.app.state.templates


@router.get("/chat", response_class=HTMLResponse)
async def quick_chat_page(
    request: Request,
    guard: AuthzGuard = Depends(requires(AGENT, EXECUTE)),
):
    """Quick Chat page — auto-detect provider and start chatting."""
    from initrunner.services.providers import detect_provider_and_model

    detected = await asyncio.to_thread(detect_provider_and_model)
    provider_detected = detected is not None
    model_name = f"{detected.provider}:{detected.model}" if detected else ""

    # Check if any roles exist (for sense UI)
    registry = request.app.state.role_registry
    discovered = await asyncio.to_thread(registry.discover)
    has_roles = any(d.role is not None for d in discovered)

    return _templates(request).TemplateResponse(
        request,
        "chat/quick.html",
        {
            "provider_detected": provider_detected,
            "model_name": model_name,
            "active_page": "chat",
            "has_roles": has_roles,
        },
    )


@router.get("/chat/stream")
async def quick_chat_stream(
    request: Request,
    prompt: str,
    session_id: str | None = None,
    guard: AuthzGuard = Depends(requires(AGENT, EXECUTE)),
):
    """SSE streaming for ephemeral quick-chat agent."""
    sid = session_id or generate_id()
    session = sessions.get(sid)

    if session is None:
        from initrunner.services.execution import build_agent_from_role_sync
        from initrunner.services.providers import build_quick_chat_role_sync

        try:
            role, _prov, _mod = await run_in_thread(
                build_quick_chat_role_sync, error_msg="Failed to detect provider"
            )
            agent = await run_in_thread(
                build_agent_from_role_sync, role, error_msg="Failed to build agent"
            )
        except Exception:
            return error_stream_response("No API key configured")

        session = sessions.create(sid, _QUICK_CHAT_ROLE_ID, agent, role)

    # Resolve attachments
    attachment_ids_param = request.query_params.get("attachment_ids")
    attachment_urls_param = request.query_params.get("attachment_urls")
    attachments, resolved_paths = await resolve_attachments(
        attachment_ids_param, attachment_urls_param
    )

    if attachments:
        from initrunner.agent.prompt import build_multimodal_prompt

        try:
            user_prompt = build_multimodal_prompt(prompt, attachments)
        except (FileNotFoundError, ValueError) as exc:
            return error_stream_response(str(exc))
        finally:
            for p in resolved_paths:
                try:
                    Path(p).unlink(missing_ok=True)
                except OSError:
                    pass
    else:
        user_prompt = prompt

    return build_sse_stream(
        session,
        sid,
        user_prompt,
        request,
        persist_memory=False,
        error_label="Quick chat stream error",
    )


@router.post("/chat/sense")
async def quick_chat_sense(
    request: Request,
    guard: AuthzGuard = Depends(requires(AGENT, READ)),
):
    """Accept prompt, return matched role JSON."""
    body = await request.json()
    prompt = body.get("prompt", "").strip()
    if not prompt:
        return JSONResponse({"error": "Prompt is required"}, status_code=400)

    from initrunner.services.role_selector import NoRolesFoundError, select_role_sync

    try:
        result = await asyncio.to_thread(select_role_sync, prompt)
    except NoRolesFoundError:
        return JSONResponse({"error": "No roles found"}, status_code=404)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)

    return JSONResponse(
        {
            "role_id": role_path_to_id(result.candidate.path),
            "name": result.candidate.name,
            "description": result.candidate.description,
            "method": result.method,
            "score": round(result.top_score, 2),
        }
    )


@router.post("/chat/upload")
async def quick_chat_upload(
    request: Request,
    guard: AuthzGuard = Depends(requires(AGENT, EXECUTE)),
):
    """Upload files for quick-chat attachment staging."""
    return await stage_upload(request)
