"""Chat HTML page + SSE streaming endpoint."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse

from initrunner._ids import generate_id
from initrunner.api._helpers import load_role_async, resolve_role_path, run_in_thread
from initrunner.api._streaming import (
    build_sse_stream,
    error_stream_response,
    resolve_attachments,
    stage_upload,
)
from initrunner.api.state import sessions

router = APIRouter(tags=["chat-ui"])
_logger = logging.getLogger(__name__)


@router.get("/roles/{role_id}/chat", response_class=HTMLResponse)
async def chat_page(request: Request, role_id: str):
    """Chat interface page."""
    role_path = await resolve_role_path(request, role_id)
    role = await load_role_async(role_path)

    model_name = role.spec.model.to_model_string()
    has_memory = role.spec.memory is not None
    session_token_budget = role.spec.guardrails.session_token_budget

    return request.app.state.templates.TemplateResponse(
        request,
        "chat/page.html",
        {
            "role_id": role_id,
            "role_name": role.metadata.name,
            "history": [],
            "active_page": "roles",
            "model_name": model_name,
            "has_memory": has_memory,
            "session_token_budget": session_token_budget,
        },
    )


@router.post("/roles/{role_id}/chat/upload")
async def chat_upload(request: Request, role_id: str):
    """Upload files for attachment staging. Returns JSON list of attachment IDs."""
    return await stage_upload(request)


@router.get("/roles/{role_id}/chat/stream")
async def chat_stream(
    request: Request,
    role_id: str,
    prompt: str = Query(..., min_length=1, max_length=100_000),
    session_id: str | None = Query(None),
    attachment_ids: str | None = Query(None),
    attachment_urls: str | None = Query(None),
):
    """SSE streaming chat endpoint.

    Streams token chunks as SSE ``message`` events, then sends ``event: close``
    with stats JSON when complete.  Supports multimodal attachments via
    ``attachment_ids`` (from upload endpoint) and ``attachment_urls`` params.
    """
    role_path = await resolve_role_path(request, role_id)

    # Resolve or create session
    sid = session_id or generate_id()
    session = sessions.get(sid)

    if session is None:
        # Try to recover from SQLite if session_id was provided
        if session_id:
            from initrunner.services.execution import build_agent_sync
            from initrunner.services.memory import load_session_by_id_sync

            role, agent = await run_in_thread(
                build_agent_sync, role_path, error_msg="Failed to build agent"
            )

            recovered = None
            if role.spec.memory is not None:
                recovered = await asyncio.to_thread(load_session_by_id_sync, role, session_id)
            session = sessions.create(
                sid, role_id, agent, role, role_path, message_history=recovered
            )
        else:
            from initrunner.services.execution import build_agent_sync as _build_agent

            role, agent = await run_in_thread(
                _build_agent, role_path, error_msg="Failed to build agent"
            )

            session = sessions.create(sid, role_id, agent, role, role_path)

    # Resolve attachments into a multimodal prompt if present
    attachments, resolved_paths = await resolve_attachments(attachment_ids, attachment_urls)

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
        persist_memory=session.role.spec.memory is not None,
        error_label=f"Chat stream error for role {role_id}",
    )


# ---------------------------------------------------------------------------
# Session history API endpoints
# ---------------------------------------------------------------------------


@router.get("/roles/{role_id}/chat/sessions")
async def list_chat_sessions(request: Request, role_id: str):
    """List stored sessions for a role."""
    role_path = await resolve_role_path(request, role_id)

    from initrunner.services.memory import list_sessions_sync

    role = await load_role_async(role_path)
    if role.spec.memory is None:
        return JSONResponse([])

    summaries = await asyncio.to_thread(list_sessions_sync, role)
    return JSONResponse(
        [
            {
                "session_id": s.session_id,
                "timestamp": s.timestamp,
                "message_count": s.message_count,
                "preview": s.preview,
            }
            for s in summaries
        ]
    )


@router.delete("/roles/{role_id}/chat/sessions/{session_id}")
async def delete_chat_session(request: Request, role_id: str, session_id: str):
    """Delete a stored session."""
    role_path = await resolve_role_path(request, role_id)

    from initrunner.services.memory import delete_session_sync

    role = await load_role_async(role_path)
    ok = await asyncio.to_thread(delete_session_sync, role, session_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Session not found")
    return JSONResponse({"ok": True})


@router.get("/roles/{role_id}/chat/sessions/{session_id}/messages")
async def get_session_messages(request: Request, role_id: str, session_id: str):
    """Load messages for a specific session."""
    from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, UserPromptPart

    from initrunner.agent.prompt import render_content_as_text

    def _to_json(messages):
        result = []
        for msg in messages:
            if isinstance(msg, ModelRequest):
                for part in msg.parts:
                    if isinstance(part, UserPromptPart):
                        if isinstance(part.content, str):
                            content = part.content
                        elif isinstance(part.content, list):
                            content = " ".join(
                                render_content_as_text(item) for item in part.content
                            )
                        else:
                            content = str(part.content)
                        result.append({"role": "user", "content": content})
            elif isinstance(msg, ModelResponse):
                for part in msg.parts:
                    if isinstance(part, TextPart):
                        result.append({"role": "assistant", "content": part.content})
        return result

    # 1. Check in-memory sessions first (works for ALL roles)
    session = sessions.get(session_id)
    if session is not None and session.message_history:
        return JSONResponse(_to_json(session.message_history))

    # 2. Fall back to SQLite (roles with memory configured)
    role_path = await resolve_role_path(request, role_id)

    from initrunner.services.memory import load_session_by_id_sync

    role = await load_role_async(role_path)
    messages = await asyncio.to_thread(load_session_by_id_sync, role, session_id)
    if messages is None:
        raise HTTPException(status_code=404, detail="Session not found")

    return JSONResponse(_to_json(messages))
