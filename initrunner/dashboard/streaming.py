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
    from initrunner.compose.schema import ComposeDefinition
    from initrunner.team.schema import TeamDefinition

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

    try:
        role, agent = await asyncio.to_thread(
            build_agent_sync, role_path, model_override=model_override
        )
    except Exception as exc:
        _logger.error("Agent build failed: %s", exc)
        yield f"data: {json.dumps({'type': 'error', 'data': str(exc)})}\n\n"
        return

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
        result, new_messages = await stream_task

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


async def stream_compose_run_sse(
    compose: ComposeDefinition,
    base_dir: Path,
    prompt: str,
    *,
    audit_logger: AuditLogger | None = None,
    message_history: list[ModelMessage] | None = None,
) -> AsyncIterator[str]:
    """SSE generator yielding service_start/service_complete/result/error events.

    Runs ``run_compose_once_sync`` in a thread pool.  Service start/complete
    callbacks push progress events to an ``asyncio.Queue``.
    """
    from initrunner.agent.executor import RunResult
    from initrunner.services.compose import run_compose_once_sync

    loop = asyncio.get_running_loop()
    event_queue: asyncio.Queue[str | None] = asyncio.Queue(maxsize=_TOKEN_QUEUE_MAX)

    def on_service_start(name: str) -> None:
        evt = json.dumps({"type": "service_start", "data": name})
        try:
            loop.call_soon_threadsafe(event_queue.put_nowait, f"data: {evt}\n\n")
        except RuntimeError:
            pass

    def on_service_complete(name: str, result: RunResult) -> None:
        evt = json.dumps(
            {
                "type": "service_complete",
                "data": {
                    "service_name": name,
                    "output": result.output[:500],
                    "duration_ms": result.duration_ms,
                    "tokens_in": result.tokens_in,
                    "tokens_out": result.tokens_out,
                    "success": result.success,
                    "error": result.error,
                },
            }
        )
        try:
            loop.call_soon_threadsafe(event_queue.put_nowait, f"data: {evt}\n\n")
        except RuntimeError:
            pass

    def run_compose():
        try:
            return run_compose_once_sync(
                compose,
                base_dir,
                prompt,
                message_history=message_history,
                audit_logger=audit_logger,
                on_service_start=on_service_start,
                on_service_complete=on_service_complete,
            )
        finally:
            try:
                loop.call_soon_threadsafe(event_queue.put_nowait, None)
            except RuntimeError:
                pass

    compose_task = loop.run_in_executor(None, run_compose)

    # Forward progress events as SSE
    heartbeat_counter = 0
    while not compose_task.done():
        try:
            event = await asyncio.wait_for(event_queue.get(), timeout=0.1)
            if event is None:
                break
            yield event
            heartbeat_counter = 0
        except TimeoutError:
            heartbeat_counter += 1
            if heartbeat_counter >= _HEARTBEAT_INTERVAL:
                yield ": heartbeat\n\n"
                heartbeat_counter = 0

    # Drain remaining events
    while not event_queue.empty():
        event = event_queue.get_nowait()
        if event is None:
            break
        yield event

    # Emit final result or error
    try:
        compose_result = await compose_task

        # Serialize entry service message history
        serialized_history = None
        if compose_result.entry_messages and compose_result.success:
            from pydantic_ai.messages import ModelMessagesTypeAdapter

            serialized_history = ModelMessagesTypeAdapter.dump_json(
                compose_result.entry_messages
            ).decode("utf-8")

        payload = {
            "output": compose_result.output,
            "output_mode": compose_result.output_mode,
            "final_service_name": compose_result.final_service_name,
            "steps": [
                {
                    "service_name": s.service_name,
                    "output": s.output,
                    "tokens_in": s.tokens_in,
                    "tokens_out": s.tokens_out,
                    "duration_ms": s.duration_ms,
                    "tool_calls": s.tool_calls,
                    "tool_call_names": s.tool_call_names,
                    "success": s.success,
                    "error": s.error,
                }
                for s in compose_result.steps
            ],
            "tokens_in": compose_result.total_tokens_in,
            "tokens_out": compose_result.total_tokens_out,
            "total_tokens": compose_result.total_tokens_in + compose_result.total_tokens_out,
            "duration_ms": compose_result.total_duration_ms,
            "success": compose_result.success,
            "error": compose_result.error,
            "message_history": serialized_history,
        }
        yield f"data: {json.dumps({'type': 'result', 'data': payload})}\n\n"
    except Exception as exc:
        _logger.exception("Error during compose SSE streaming")
        yield f"data: {json.dumps({'type': 'error', 'data': str(exc)})}\n\n"


async def stream_team_run_sse(
    team: TeamDefinition,
    team_dir: Path,
    prompt: str,
    *,
    audit_logger: AuditLogger | None = None,
) -> AsyncIterator[str]:
    """SSE generator yielding persona_start/persona_complete/result/error events.

    Runs ``run_team_dispatch`` in a thread pool. Persona start/complete
    callbacks push progress events to an ``asyncio.Queue``.
    """
    from initrunner.agent.executor import RunResult
    from initrunner.team.runner import run_team_dispatch

    loop = asyncio.get_running_loop()
    event_queue: asyncio.Queue[str | None] = asyncio.Queue(maxsize=_TOKEN_QUEUE_MAX)

    def on_persona_start(name: str) -> None:
        evt = json.dumps({"type": "persona_start", "data": name})
        try:
            loop.call_soon_threadsafe(event_queue.put_nowait, f"data: {evt}\n\n")
        except RuntimeError:
            pass

    def on_persona_complete(name: str, result: RunResult) -> None:
        evt = json.dumps(
            {
                "type": "persona_complete",
                "data": {
                    "persona_name": name,
                    "output": result.output[:500],
                    "duration_ms": result.duration_ms,
                    "tokens_in": result.tokens_in,
                    "tokens_out": result.tokens_out,
                    "tool_calls": result.tool_calls,
                    "tool_call_names": result.tool_call_names,
                    "success": result.success,
                    "error": result.error,
                },
            }
        )
        try:
            loop.call_soon_threadsafe(event_queue.put_nowait, f"data: {evt}\n\n")
        except RuntimeError:
            pass

    def run_team():
        try:
            return run_team_dispatch(
                team,
                prompt,
                team_dir=team_dir,
                audit_logger=audit_logger,
                on_persona_start=on_persona_start,
                on_persona_complete=on_persona_complete,
            )
        finally:
            try:
                loop.call_soon_threadsafe(event_queue.put_nowait, None)
            except RuntimeError:
                pass

    team_task = loop.run_in_executor(None, run_team)

    # Forward progress events as SSE
    heartbeat_counter = 0
    while not team_task.done():
        try:
            event = await asyncio.wait_for(event_queue.get(), timeout=0.1)
            if event is None:
                break
            yield event
            heartbeat_counter = 0
        except TimeoutError:
            heartbeat_counter += 1
            if heartbeat_counter >= _HEARTBEAT_INTERVAL:
                yield ": heartbeat\n\n"
                heartbeat_counter = 0

    # Drain remaining events
    while not event_queue.empty():
        event = event_queue.get_nowait()
        if event is None:
            break
        yield event

    # Emit final result or error
    try:
        team_result = await team_task

        payload = {
            "team_run_id": team_result.team_run_id,
            "output": team_result.final_output,
            "steps": [
                {
                    "persona_name": name,
                    "output": res.output,
                    "tokens_in": res.tokens_in,
                    "tokens_out": res.tokens_out,
                    "duration_ms": res.duration_ms,
                    "tool_calls": res.tool_calls,
                    "tool_call_names": res.tool_call_names,
                    "success": res.success,
                    "error": res.error,
                }
                for name, res in zip(
                    team_result.agent_names, team_result.agent_results, strict=True
                )
            ],
            "tokens_in": team_result.total_tokens_in,
            "tokens_out": team_result.total_tokens_out,
            "total_tokens": team_result.total_tokens,
            "duration_ms": team_result.total_duration_ms,
            "success": team_result.success,
            "error": team_result.error,
        }
        yield f"data: {json.dumps({'type': 'result', 'data': payload})}\n\n"
    except Exception as exc:
        _logger.exception("Error during team SSE streaming")
        yield f"data: {json.dumps({'type': 'error', 'data': str(exc)})}\n\n"


async def stream_ingest_sse(
    role_path: Path,
    *,
    force: bool = False,
) -> AsyncIterator[str]:
    """SSE generator yielding progress/result/error events for ingestion.

    Runs ``run_ingest_sync`` in a thread pool.  The ``progress_callback``
    pushes per-file events to an ``asyncio.Queue`` via ``call_soon_threadsafe``.
    """
    from initrunner.services.operations import run_ingest_sync

    loop = asyncio.get_running_loop()
    event_queue: asyncio.Queue[str | None] = asyncio.Queue(maxsize=_TOKEN_QUEUE_MAX)

    def on_progress(path: Path, status) -> None:
        evt = json.dumps({"type": "progress", "data": {"path": str(path), "status": str(status)}})
        try:
            loop.call_soon_threadsafe(event_queue.put_nowait, f"data: {evt}\n\n")
        except RuntimeError:
            pass

    def run_ingest():
        from initrunner.agent.loader import load_role, resolve_role_model

        role = resolve_role_model(load_role(role_path), role_path)
        try:
            return run_ingest_sync(role, role_path, force=force, progress_callback=on_progress)
        finally:
            loop.call_soon_threadsafe(event_queue.put_nowait, None)

    ingest_task = loop.run_in_executor(None, run_ingest)

    heartbeat_counter = 0
    while not ingest_task.done():
        try:
            event = await asyncio.wait_for(event_queue.get(), timeout=0.1)
            if event is None:
                break
            yield event
            heartbeat_counter = 0
        except TimeoutError:
            heartbeat_counter += 1
            if heartbeat_counter >= _HEARTBEAT_INTERVAL:
                yield ": heartbeat\n\n"
                heartbeat_counter = 0

    # Drain remaining events
    while not event_queue.empty():
        event = event_queue.get_nowait()
        if event is None:
            break
        yield event

    # Emit final result or error
    try:
        stats = await ingest_task
        payload = {
            "new": stats.new if stats else 0,
            "updated": stats.updated if stats else 0,
            "skipped": stats.skipped if stats else 0,
            "errored": stats.errored if stats else 0,
            "total_chunks": stats.total_chunks if stats else 0,
            "file_results": [
                {
                    "path": str(r.path),
                    "status": str(r.status),
                    "chunks": r.chunks,
                    "error": r.error,
                }
                for r in (stats.file_results if stats else [])
            ],
        }
        yield f"data: {json.dumps({'type': 'result', 'data': payload})}\n\n"
    except Exception as exc:
        _logger.exception("Error during ingest SSE streaming")
        yield f"data: {json.dumps({'type': 'error', 'data': str(exc)})}\n\n"
