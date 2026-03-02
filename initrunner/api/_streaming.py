"""Shared SSE streaming, upload staging, and attachment resolution utilities.

Used by both ``chat_ui`` and ``quick_chat`` route modules to avoid
duplicating ~200 lines of identical logic.
"""

from __future__ import annotations

import asyncio
import json
import logging
import tempfile
import time
from pathlib import Path
from urllib.parse import urlparse

from fastapi import Request
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.datastructures import UploadFile

from initrunner._ids import generate_id
from initrunner.agent._urls import validate_url_ssrf

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

_TOKEN_QUEUE_MAX = 10_000
_MAX_API_HISTORY = 40
_HEARTBEAT_INTERVAL = 100  # iterations (~10s at 0.1s poll)
_UPLOAD_MAX_FILE_SIZE = 20 * 1024 * 1024  # 20 MB
_UPLOAD_TTL_SECONDS = 300  # 5 minutes

# ---------------------------------------------------------------------------
# Single upload staging store (replaces two separate dicts in chat_ui /
# quick_chat).  Safe because upload IDs are globally unique.
# ---------------------------------------------------------------------------

_upload_staging: dict[str, tuple[str, float]] = {}
_upload_lock = asyncio.Lock()


# ---------------------------------------------------------------------------
# Upload handler
# ---------------------------------------------------------------------------


async def stage_upload(request: Request) -> JSONResponse:
    """Stage uploaded files and return their attachment IDs.

    Shared implementation for ``chat_upload()`` and ``quick_chat_upload()``.
    """
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


# ---------------------------------------------------------------------------
# Attachment resolution
# ---------------------------------------------------------------------------


async def resolve_attachments(
    attachment_ids: str | None,
    attachment_urls: str | None,
) -> tuple[list[str], list[str]]:
    """Pop staged uploads and split URL params into attachment lists.

    Returns ``(attachments, resolved_paths)`` where *resolved_paths* contains
    only the local file paths that should be cleaned up after use.
    """
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
            if not url:
                continue
            # Only allow http/https schemes
            try:
                scheme = urlparse(url).scheme.lower()
            except Exception:
                _logger.warning("Attachment URL rejected (invalid URL): %s", url)
                continue
            if scheme not in ("http", "https"):
                _logger.warning("Attachment URL rejected (scheme %r): %s", scheme, url)
                continue
            # Block SSRF (private/internal IPs)
            ssrf_error = validate_url_ssrf(url)
            if ssrf_error:
                _logger.warning("Attachment URL rejected (%s): %s", ssrf_error, url)
                continue
            attachments.append(url)

    return attachments, resolved_paths


# ---------------------------------------------------------------------------
# SSE stream builder
# ---------------------------------------------------------------------------


def error_stream_response(error_msg: str) -> StreamingResponse:
    """Return a single-event SSE stream containing only an error close event."""

    async def _stream():
        yield f"event: close\ndata: {json.dumps({'error': error_msg})}\n\n"

    return StreamingResponse(
        _stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


def build_sse_stream(
    session,  # ChatSession
    sid: str,
    user_prompt,
    request: Request,
    *,
    persist_memory: bool,
    error_label: str,
) -> StreamingResponse:
    """Build and return a ``StreamingResponse`` that streams agent tokens as SSE.

    Parameters
    ----------
    session:
        The ``ChatSession`` object (has ``.agent``, ``.role``,
        ``.message_history``).
    sid:
        Session ID string.
    user_prompt:
        The (possibly multimodal) prompt to send to the agent.
    request:
        The FastAPI request (used to read ``app.state.audit_logger``).
    persist_memory:
        Whether to persist the session to SQLite after the run.
    error_label:
        Human-readable label for the logger on error
        (e.g. ``"Chat stream error for role X"``).
    """

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
            if persist_memory:
                try:
                    from initrunner.services.memory import save_session_sync

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
            _logger.exception(error_label)
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
