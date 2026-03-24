"""SSE streaming helper -- token queue pattern from server/app.py."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pydantic_ai.messages import ModelMessage

    from initrunner.audit.logger import AuditLogger

_logger = logging.getLogger(__name__)
_TOKEN_QUEUE_MAX = 65536
_HEARTBEAT_INTERVAL = 10  # heartbeat every ~1s (10 * 0.1s timeout)


async def stream_run_sse(
    role_path: Path,
    prompt: str,
    *,
    audit_logger: AuditLogger | None = None,
    model_override: str | None = None,
    message_history: list[ModelMessage] | None = None,
) -> AsyncIterator[str]:
    """SSE generator yielding token/result/error events.

    Replicates the proven pattern from ``initrunner/server/app.py:279-348``:
    sync ``execute_run_stream_sync`` runs in a thread pool, pushes tokens
    to an ``asyncio.Queue`` via ``call_soon_threadsafe``.
    """
    from initrunner.services.execution import build_agent_sync, execute_run_stream_sync

    loop = asyncio.get_running_loop()
    token_queue: asyncio.Queue[str | None] = asyncio.Queue(maxsize=_TOKEN_QUEUE_MAX)

    role, agent = await asyncio.to_thread(
        build_agent_sync, role_path, model_override=model_override
    )

    def on_token(chunk: str) -> None:
        try:
            loop.call_soon_threadsafe(token_queue.put_nowait, chunk)
        except RuntimeError:
            pass  # loop closed -- stream tearing down

    def run_stream():
        try:
            return execute_run_stream_sync(
                agent,
                role,
                prompt,
                audit_logger=audit_logger,
                on_token=on_token,
                message_history=message_history,
            )
        finally:
            loop.call_soon_threadsafe(token_queue.put_nowait, None)

    stream_task = loop.run_in_executor(None, run_stream)

    # Forward tokens as SSE events
    heartbeat_counter = 0
    while not stream_task.done():
        try:
            token = await asyncio.wait_for(token_queue.get(), timeout=0.1)
            if token is None:
                break
            yield f"data: {json.dumps({'type': 'token', 'data': token})}\n\n"
            heartbeat_counter = 0
        except TimeoutError:
            heartbeat_counter += 1
            if heartbeat_counter >= _HEARTBEAT_INTERVAL:
                yield ": heartbeat\n\n"
                heartbeat_counter = 0

    # Drain remaining tokens
    while not token_queue.empty():
        token = token_queue.get_nowait()
        if token is None:
            break
        yield f"data: {json.dumps({'type': 'token', 'data': token})}\n\n"

    # Emit final result or error
    try:
        result, new_messages = stream_task.result()

        # Serialize trimmed history on success
        serialized_history = None
        if result.success:
            from pydantic_ai.messages import ModelMessagesTypeAdapter

            from initrunner.agent.history import session_limits, trim_message_history

            _, max_history = session_limits(role)
            trimmed = trim_message_history(new_messages, max_history)
            serialized_history = ModelMessagesTypeAdapter.dump_json(trimmed).decode("utf-8")

        payload = {
            "run_id": result.run_id,
            "output": result.output,
            "tokens_in": result.tokens_in,
            "tokens_out": result.tokens_out,
            "total_tokens": result.total_tokens,
            "tool_calls": result.tool_calls,
            "tool_call_names": result.tool_call_names,
            "duration_ms": result.duration_ms,
            "success": result.success,
            "error": result.error,
            "message_history": serialized_history,
        }
        event = json.dumps({"type": "result", "data": payload})
        yield f"data: {event}\n\n"
    except Exception as exc:
        _logger.exception("Error during SSE streaming")
        yield f"data: {json.dumps({'type': 'error', 'data': str(exc)})}\n\n"
