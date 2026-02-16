"""Chat HTML page + SSE streaming endpoint."""

from __future__ import annotations

import asyncio
import json
import logging
import tempfile
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from starlette.datastructures import UploadFile

from initrunner._ids import generate_id
from initrunner.api._helpers import resolve_role_path, run_in_thread
from initrunner.api.state import sessions

router = APIRouter(tags=["chat-ui"])
_logger = logging.getLogger(__name__)

_TOKEN_QUEUE_MAX = 10_000
_MAX_API_HISTORY = 40
_HEARTBEAT_INTERVAL = 100  # iterations (~10s at 0.1s poll)
_UPLOAD_MAX_FILE_SIZE = 20 * 1024 * 1024  # 20 MB
_UPLOAD_TTL_SECONDS = 300  # 5 minutes

# In-memory staging store for uploaded attachments: id → (path, expires_at)
_upload_staging: dict[str, tuple[str, float]] = {}
_upload_lock = asyncio.Lock()


@router.get("/roles/{role_id}/chat", response_class=HTMLResponse)
async def chat_page(request: Request, role_id: str):
    """Chat interface page."""
    role_path = await resolve_role_path(request, role_id)

    from initrunner.agent.loader import load_role

    role = await asyncio.to_thread(load_role, role_path)

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
    form = await request.form()
    attachment_ids: list[str] = []

    async with _upload_lock:
        # Prune expired entries
        now = time.time()
        expired = [k for k, (_, exp) in _upload_staging.items() if exp < now]
        for k in expired:
            path = _upload_staging.pop(k)[0]
            try:
                Path(path).unlink(missing_ok=True)
            except OSError:
                pass

        for key in form:
            upload = form[key]
            if not isinstance(upload, UploadFile) or upload.filename is None:
                continue
            data = await upload.read()
            if len(data) > _UPLOAD_MAX_FILE_SIZE:
                return JSONResponse(
                    {"error": f"File too large: {upload.filename} (max 20 MB)"},
                    status_code=400,
                )
            # Write to temp file preserving extension
            suffix = Path(upload.filename).suffix
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix, prefix="ir_upload_")
            tmp.write(data)
            tmp.close()

            aid = generate_id()
            _upload_staging[aid] = (tmp.name, time.time() + _UPLOAD_TTL_SECONDS)
            attachment_ids.append(aid)

    return JSONResponse({"attachment_ids": attachment_ids})


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
            from initrunner.services import build_agent_sync, load_session_by_id_sync

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
            from initrunner.services import build_agent_sync

            role, agent = await run_in_thread(
                build_agent_sync, role_path, error_msg="Failed to build agent"
            )

            session = sessions.create(sid, role_id, agent, role, role_path)

    # Resolve attachments into a multimodal prompt if present
    attachments: list[str] = []
    resolved_paths: list[str] = []
    if attachment_ids:
        async with _upload_lock:
            for aid in attachment_ids.split(","):
                aid = aid.strip()
                if aid in _upload_staging:
                    path, _ = _upload_staging.pop(aid)
                    attachments.append(path)
                    resolved_paths.append(path)
    if attachment_urls:
        for url in attachment_urls.split(","):
            url = url.strip()
            if url:
                attachments.append(url)

    if attachments:
        from initrunner.agent.prompt import build_multimodal_prompt

        try:
            user_prompt = build_multimodal_prompt(prompt, attachments)
        except (FileNotFoundError, ValueError) as exc:
            error_msg = str(exc)

            async def _error_stream():
                yield f"event: close\ndata: {json.dumps({'error': error_msg})}\n\n"

            return StreamingResponse(
                _error_stream(),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
            )
        finally:
            for p in resolved_paths:
                try:
                    Path(p).unlink(missing_ok=True)
                except OSError:
                    pass
    else:
        user_prompt = prompt

    async def event_stream():
        from initrunner.services import execute_run_stream_sync

        token_queue: asyncio.Queue[str | None] = asyncio.Queue(maxsize=_TOKEN_QUEUE_MAX)
        loop = asyncio.get_event_loop()

        def on_token(chunk: str) -> None:
            try:
                loop.call_soon_threadsafe(token_queue.put_nowait, chunk)
            except asyncio.QueueFull:
                pass

        audit_logger = getattr(request.app.state, "audit_logger", None)

        def run_stream():
            return execute_run_stream_sync(
                session.agent,
                session.role,
                user_prompt,
                message_history=session.message_history or None,
                on_token=on_token,
                audit_logger=audit_logger,
            )

        stream_task = loop.run_in_executor(None, run_stream)

        timeout = session.role.spec.guardrails.timeout_seconds
        deadline = time.monotonic() + timeout

        # Forward tokens as SSE data events
        heartbeat_counter = 0
        while not stream_task.done():
            if time.monotonic() > deadline:
                stream_task.cancel()
                err = {"error": f"Run timed out after {timeout}s"}
                yield f"event: close\ndata: {json.dumps(err)}\n\n"
                return
            try:
                token = await asyncio.wait_for(token_queue.get(), timeout=0.1)
                if token is not None:
                    # Default SSE event type is "message"
                    yield f"data: {token}\n\n"
                    heartbeat_counter = 0
            except TimeoutError:
                heartbeat_counter += 1
                if heartbeat_counter >= _HEARTBEAT_INTERVAL:
                    yield ": heartbeat\n\n"
                    heartbeat_counter = 0

        # Drain remaining tokens
        while not token_queue.empty():
            token = token_queue.get_nowait()
            if token is not None:
                yield f"data: {token}\n\n"

        # Get result and send close event
        try:
            result, new_messages = await stream_task
            session.message_history = new_messages
            if len(session.message_history) > _MAX_API_HISTORY:
                session.message_history = session.message_history[-_MAX_API_HISTORY:]

            # Persist to SQLite if memory is configured
            if session.role.spec.memory is not None:
                try:
                    from initrunner.services import save_session_sync

                    await asyncio.to_thread(
                        save_session_sync, session.role, sid, session.message_history
                    )
                except Exception:
                    _logger.warning("Failed to persist session %s to SQLite", sid, exc_info=True)

            stats = {
                "session_id": sid,
                "total_tokens": result.total_tokens,
                "tokens_in": result.tokens_in,
                "tokens_out": result.tokens_out,
                "duration_ms": result.duration_ms,
                "success": result.success,
            }
            if result.error:
                stats["error"] = result.error
            yield f"event: close\ndata: {json.dumps(stats)}\n\n"
        except (Exception, asyncio.CancelledError) as e:
            _logger.exception("Chat stream error for role %s", role_id)
            yield f"event: close\ndata: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------------------
# Session history API endpoints
# ---------------------------------------------------------------------------


@router.get("/roles/{role_id}/chat/sessions")
async def list_chat_sessions(request: Request, role_id: str):
    """List stored sessions for a role."""
    role_path = await resolve_role_path(request, role_id)

    from initrunner.agent.loader import load_role
    from initrunner.services import list_sessions_sync

    role = await asyncio.to_thread(load_role, role_path)
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

    from initrunner.agent.loader import load_role
    from initrunner.services import delete_session_sync

    role = await asyncio.to_thread(load_role, role_path)
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

    from initrunner.agent.loader import load_role
    from initrunner.services import load_session_by_id_sync

    role = await asyncio.to_thread(load_role, role_path)
    messages = await asyncio.to_thread(load_session_by_id_sync, role, session_id)
    if messages is None:
        raise HTTPException(status_code=404, detail="Session not found")

    return JSONResponse(_to_json(messages))
