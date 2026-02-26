"""Quick Chat + Sense routes — provider-detected ephemeral chat."""

from __future__ import annotations

import asyncio
import json
import logging
import tempfile
import time
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from starlette.datastructures import UploadFile

from initrunner._ids import generate_id
from initrunner.api._helpers import run_in_thread
from initrunner.api.state import role_path_to_id, sessions

router = APIRouter(tags=["quick-chat"])
_logger = logging.getLogger(__name__)

_TOKEN_QUEUE_MAX = 10_000
_MAX_API_HISTORY = 40
_HEARTBEAT_INTERVAL = 100
_UPLOAD_MAX_FILE_SIZE = 20 * 1024 * 1024  # 20 MB
_UPLOAD_TTL_SECONDS = 300

# In-memory staging for quick-chat uploads
_upload_staging: dict[str, tuple[str, float]] = {}
_upload_lock = asyncio.Lock()

_QUICK_CHAT_ROLE_ID = "__quick_chat__"


def _templates(request: Request):
    return request.app.state.templates


@router.get("/chat", response_class=HTMLResponse)
async def quick_chat_page(request: Request):
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

            async def _error():
                yield 'event: close\ndata: {"error": "No API key configured"}\n\n'

            return StreamingResponse(
                _error(),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
            )

        session = sessions.create(sid, _QUICK_CHAT_ROLE_ID, agent, role)

    # Resolve attachments
    attachments: list[str] = []
    resolved_paths: list[str] = []

    attachment_ids_param = request.query_params.get("attachment_ids")
    if attachment_ids_param:
        async with _upload_lock:
            for aid in attachment_ids_param.split(","):
                aid = aid.strip()
                if aid in _upload_staging:
                    path, _ = _upload_staging.pop(aid)
                    attachments.append(path)
                    resolved_paths.append(path)

    attachment_urls_param = request.query_params.get("attachment_urls")
    if attachment_urls_param:
        for url in attachment_urls_param.split(","):
            url = url.strip()
            if url:
                attachments.append(url)

    if attachments:
        from initrunner.agent.prompt import build_multimodal_prompt

        try:
            user_prompt = build_multimodal_prompt(prompt, attachments)
        except (FileNotFoundError, ValueError) as exc:
            error_msg = str(exc)

            async def _err_stream():
                yield f"event: close\ndata: {json.dumps({'error': error_msg})}\n\n"

            return StreamingResponse(
                _err_stream(),
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
        from initrunner.services.execution import execute_run_stream_sync

        token_queue: asyncio.Queue[str | None] = asyncio.Queue(maxsize=_TOKEN_QUEUE_MAX)
        loop = asyncio.get_running_loop()

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
                    yield f"data: {token}\n\n"
                    heartbeat_counter = 0
            except TimeoutError:
                heartbeat_counter += 1
                if heartbeat_counter >= _HEARTBEAT_INTERVAL:
                    yield ": heartbeat\n\n"
                    heartbeat_counter = 0

        while not token_queue.empty():
            token = token_queue.get_nowait()
            if token is not None:
                yield f"data: {token}\n\n"

        try:
            result, new_messages = await stream_task
            session.message_history = new_messages
            if len(session.message_history) > _MAX_API_HISTORY:
                session.message_history = session.message_history[-_MAX_API_HISTORY:]

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
            _logger.exception("Quick chat stream error")
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


@router.post("/chat/sense")
async def quick_chat_sense(request: Request):
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
async def quick_chat_upload(request: Request):
    """Upload files for quick-chat attachment staging."""
    form = await request.form()
    attachment_ids: list[str] = []

    async with _upload_lock:
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
            suffix = Path(upload.filename).suffix
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix, prefix="ir_upload_")
            tmp.write(data)
            tmp.close()

            aid = generate_id()
            _upload_staging[aid] = (tmp.name, time.time() + _UPLOAD_TTL_SECONDS)
            attachment_ids.append(aid)

    return JSONResponse({"attachment_ids": attachment_ids})
