"""SSE streaming helper -- token queue pattern from server/app.py."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pydantic_ai.messages import ModelMessage

    from initrunner.agent.executor import RunResult
    from initrunner.agent.schema.role import RoleDefinition
    from initrunner.audit.logger import AuditLogger
    from initrunner.flow.schema import FlowDefinition
    from initrunner.ingestion.pipeline import IngestStats
    from initrunner.team.schema import TeamDefinition

_logger = logging.getLogger(__name__)
_TOKEN_QUEUE_MAX = 65536
_HEARTBEAT_INTERVAL = 10  # heartbeat every ~1s (10 * 0.1s timeout)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _build_result_payload(
    result: RunResult,
    new_messages: list[ModelMessage],
    role: RoleDefinition,
) -> dict:
    """Build the SSE result payload dict from a RunResult."""
    from pydantic_ai.messages import ModelMessagesTypeAdapter

    from initrunner.agent.history import session_limits, trim_message_history

    serialized_history = None
    if result.success:
        _, max_history = session_limits(role)
        trimmed = trim_message_history(new_messages, max_history)
        serialized_history = ModelMessagesTypeAdapter.dump_json(trimmed).decode("utf-8")

    # Cost estimation
    cost = None
    model_spec = role.spec.model
    if model_spec and model_spec.name and model_spec.provider:
        from initrunner.dashboard.pricing import estimate_cost

        cost = estimate_cost(
            result.tokens_in,
            result.tokens_out,
            model_spec.name,
            model_spec.provider,
        )

    return {
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
        "cost": cost,
    }


def _build_ingest_payload(stats: IngestStats | None) -> dict:
    """Build the SSE result payload dict from ingestion stats."""
    return {
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


async def _sse_pump(
    queue: asyncio.Queue[str | None],
    work: asyncio.Future[Any],
    build_result: Callable[[Any], dict],
    error_context: str,
) -> AsyncIterator[str]:
    """Drain *queue* with heartbeats, await *work*, emit result.

    All items on the queue must be pre-formatted SSE ``data: ...\\n\\n``
    strings; ``None`` is the sentinel.  The pump yields them verbatim.
    """
    heartbeat_counter = 0
    while not work.done():
        try:
            event = await asyncio.wait_for(queue.get(), timeout=0.1)
            if event is None:
                break
            yield event
            heartbeat_counter = 0
        except TimeoutError:
            heartbeat_counter += 1
            if heartbeat_counter >= _HEARTBEAT_INTERVAL:
                yield ": heartbeat\n\n"
                heartbeat_counter = 0

    while not queue.empty():
        event = queue.get_nowait()
        if event is None:
            break
        yield event

    try:
        raw = await work
        payload = build_result(raw)
        yield f"data: {json.dumps({'type': 'result', 'data': payload})}\n\n"
    except Exception as exc:
        _logger.exception(error_context)
        yield f"data: {json.dumps({'type': 'error', 'data': str(exc)})}\n\n"


# ---------------------------------------------------------------------------
# Public SSE generators
# ---------------------------------------------------------------------------


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

    # Structured output doesn't support streaming -- run non-streaming
    if role.spec.output.type != "text":
        from initrunner.services.execution import execute_run_sync

        try:
            result, new_messages = await asyncio.to_thread(
                execute_run_sync,
                agent,
                role,
                prompt,
                audit_logger=audit_logger,
                message_history=message_history,
            )
            payload = _build_result_payload(result, new_messages, role)
            yield f"data: {json.dumps({'type': 'result', 'data': payload})}\n\n"
        except Exception as exc:
            _logger.exception("Error during non-streaming structured-output run")
            yield f"data: {json.dumps({'type': 'error', 'data': str(exc)})}\n\n"
        return

    # Emit initial usage event with budget + model info
    guardrails = role.spec.guardrails
    model_spec = role.spec.model
    usage_payload = json.dumps(
        {
            "type": "usage",
            "data": {
                "budget": {
                    "max_tokens": guardrails.max_tokens_per_run if guardrails else None,
                    "total_limit": guardrails.total_tokens_limit if guardrails else None,
                },
                "model": model_spec.name if model_spec else None,
                "provider": model_spec.provider if model_spec else None,
            },
        }
    )
    yield f"data: {usage_payload}\n\n"

    def on_token(chunk: str) -> None:
        formatted = f"data: {json.dumps({'type': 'token', 'data': chunk})}\n\n"
        try:
            loop.call_soon_threadsafe(token_queue.put_nowait, formatted)
        except RuntimeError:
            pass  # loop closed -- stream tearing down

    def run_stream():
        from initrunner.agent.tool_events import reset_tool_event_callback, set_tool_event_callback

        def on_tool_event(event) -> None:
            evt = json.dumps(
                {
                    "type": "tool_event",
                    "data": {
                        "tool_name": event.tool_name,
                        "status": event.status,
                        "phase": event.phase,
                        "error_summary": event.error_summary,
                        "duration_ms": event.duration_ms,
                    },
                }
            )
            try:
                loop.call_soon_threadsafe(token_queue.put_nowait, f"data: {evt}\n\n")
            except RuntimeError:
                pass

        cb_token = set_tool_event_callback(on_tool_event)
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
            reset_tool_event_callback(cb_token)
            loop.call_soon_threadsafe(token_queue.put_nowait, None)

    stream_task = loop.run_in_executor(None, run_stream)

    def _build(raw: object) -> dict:
        result, new_messages = raw  # type: ignore[misc]
        return _build_result_payload(result, new_messages, role)

    async for event in _sse_pump(token_queue, stream_task, _build, "Error during SSE streaming"):
        yield event


async def stream_flow_run_sse(
    flow: FlowDefinition,
    base_dir: Path,
    prompt: str,
    *,
    audit_logger: AuditLogger | None = None,
    message_history: list[ModelMessage] | None = None,
) -> AsyncIterator[str]:
    """SSE generator yielding agent_start/agent_complete/result/error events.

    Runs flow graph directly as an async task (no thread pool hop).
    Callbacks push progress events to an ``asyncio.Queue``.
    """
    from initrunner.agent.loader import load_role, resolve_role_model
    from initrunner.services.flow import run_flow_once_async

    event_queue: asyncio.Queue[str | None] = asyncio.Queue(maxsize=_TOKEN_QUEUE_MAX)

    # Resolve models to determine if cost estimation is possible
    resolved_models: set[tuple[str, str]] = set()
    for agent_config in flow.spec.agents.values():
        try:
            role = resolve_role_model(load_role(base_dir / agent_config.role), base_dir)
            if role.spec.model and role.spec.model.name and role.spec.model.provider:
                resolved_models.add((role.spec.model.provider, role.spec.model.name))
        except Exception:
            pass
    flow_model = resolved_models.pop() if len(resolved_models) == 1 else None

    # Emit usage event with model info (matches agent stream pattern)
    usage_payload = json.dumps(
        {
            "type": "usage",
            "data": {
                "budget": {"max_tokens": None, "total_limit": None},
                "model": flow_model[1] if flow_model else None,
                "provider": flow_model[0] if flow_model else None,
            },
        }
    )
    yield f"data: {usage_payload}\n\n"

    def on_agent_start(name: str) -> None:
        try:
            event_queue.put_nowait(f"data: {json.dumps({'type': 'agent_start', 'data': name})}\n\n")
        except asyncio.QueueFull:
            pass

    def on_agent_complete(name: str, result: RunResult) -> None:
        evt = json.dumps(
            {
                "type": "agent_complete",
                "data": {
                    "agent_name": name,
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
            event_queue.put_nowait(f"data: {evt}\n\n")
        except asyncio.QueueFull:
            pass

    def on_tool_event(agent_name: str, event: object) -> None:
        evt = json.dumps(
            {
                "type": "tool_event",
                "data": {
                    "agent_name": agent_name,
                    "tool_name": event.tool_name,  # type: ignore[union-attr]
                    "status": event.status,  # type: ignore[union-attr]
                    "phase": event.phase,  # type: ignore[union-attr]
                    "error_summary": event.error_summary,  # type: ignore[union-attr]
                    "duration_ms": event.duration_ms,  # type: ignore[union-attr]
                },
            }
        )
        try:
            event_queue.put_nowait(f"data: {evt}\n\n")
        except asyncio.QueueFull:
            pass

    async def _run_flow():
        try:
            return await run_flow_once_async(
                flow,
                base_dir,
                prompt,
                message_history=message_history,
                audit_logger=audit_logger,
                on_agent_start=on_agent_start,
                on_agent_complete=on_agent_complete,
                on_tool_event=on_tool_event,
            )
        finally:
            event_queue.put_nowait(None)

    flow_task = asyncio.create_task(_run_flow())

    def _build(raw: Any) -> dict:
        flow_result = raw

        serialized_history = None
        if flow_result.entry_messages and flow_result.success:
            from pydantic_ai.messages import ModelMessagesTypeAdapter

            serialized_history = ModelMessagesTypeAdapter.dump_json(
                flow_result.entry_messages
            ).decode("utf-8")

        cost = None
        if flow_model:
            from initrunner.dashboard.pricing import estimate_cost

            cost = estimate_cost(
                flow_result.total_tokens_in,
                flow_result.total_tokens_out,
                flow_model[1],
                flow_model[0],
            )

        return {
            "output": flow_result.output,
            "output_mode": flow_result.output_mode,
            "final_agent_name": flow_result.final_agent_name,
            "cost": cost,
            "steps": [
                {
                    "agent_name": s.agent_name,
                    "output": s.output,
                    "tokens_in": s.tokens_in,
                    "tokens_out": s.tokens_out,
                    "duration_ms": s.duration_ms,
                    "tool_calls": s.tool_calls,
                    "tool_call_names": s.tool_call_names,
                    "success": s.success,
                    "error": s.error,
                }
                for s in flow_result.steps
            ],
            "tokens_in": flow_result.total_tokens_in,
            "tokens_out": flow_result.total_tokens_out,
            "total_tokens": flow_result.total_tokens_in + flow_result.total_tokens_out,
            "duration_ms": flow_result.total_duration_ms,
            "success": flow_result.success,
            "error": flow_result.error,
            "message_history": serialized_history,
        }

    async for event in _sse_pump(event_queue, flow_task, _build, "Error during flow SSE streaming"):
        yield event


async def stream_team_run_sse(
    team: TeamDefinition,
    team_dir: Path,
    prompt: str,
    *,
    audit_logger: AuditLogger | None = None,
) -> AsyncIterator[str]:
    """SSE generator yielding persona_start/persona_complete/result/error events.

    Runs team graph directly as an async task (no thread pool hop).
    """
    from initrunner.team.graph import run_team_graph_async

    event_queue: asyncio.Queue[str | None] = asyncio.Queue(maxsize=_TOKEN_QUEUE_MAX)

    # Resolve team model for cost estimation (null if any persona overrides)
    team_model: tuple[str, str] | None = None
    team_budget: int | None = None
    try:
        personas = team.spec.personas
        if hasattr(personas, "values") and callable(personas.values):
            has_overrides = any(
                getattr(p, "model", None) is not None for p in personas.values()
            )
        else:
            has_overrides = True
        model = team.spec.model
        if (
            not has_overrides
            and model is not None
            and isinstance(getattr(model, "name", None), str)
            and isinstance(getattr(model, "provider", None), str)
        ):
            team_model = (model.provider, model.name)
        guardrails = team.spec.guardrails
        budget_val = getattr(guardrails, "team_token_budget", None)
        if isinstance(budget_val, int):
            team_budget = budget_val
    except (AttributeError, TypeError):
        pass
    usage_payload = json.dumps(
        {
            "type": "usage",
            "data": {
                "budget": {"max_tokens": None, "total_limit": team_budget},
                "model": team_model[1] if team_model else None,
                "provider": team_model[0] if team_model else None,
            },
        }
    )
    yield f"data: {usage_payload}\n\n"

    def on_persona_start(name: str) -> None:
        try:
            event_queue.put_nowait(
                f"data: {json.dumps({'type': 'persona_start', 'data': name})}\n\n"
            )
        except asyncio.QueueFull:
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
            event_queue.put_nowait(f"data: {evt}\n\n")
        except asyncio.QueueFull:
            pass

    def on_tool_event(agent_name: str, event: object) -> None:
        evt = json.dumps(
            {
                "type": "tool_event",
                "data": {
                    "agent_name": agent_name,
                    "tool_name": event.tool_name,  # type: ignore[union-attr]
                    "status": event.status,  # type: ignore[union-attr]
                    "phase": event.phase,  # type: ignore[union-attr]
                    "error_summary": event.error_summary,  # type: ignore[union-attr]
                    "duration_ms": event.duration_ms,  # type: ignore[union-attr]
                },
            }
        )
        try:
            event_queue.put_nowait(f"data: {evt}\n\n")
        except asyncio.QueueFull:
            pass

    async def _run_team():
        try:
            return await run_team_graph_async(
                team,
                prompt,
                team_dir=team_dir,
                audit_logger=audit_logger,
                on_persona_start=on_persona_start,
                on_persona_complete=on_persona_complete,
                on_tool_event=on_tool_event,
            )
        finally:
            event_queue.put_nowait(None)

    team_task = asyncio.create_task(_run_team())

    def _build(raw: Any) -> dict:
        team_result = raw

        step_entries = []
        for i, (name, res) in enumerate(
            zip(team_result.agent_names, team_result.agent_results, strict=True)
        ):
            entry = {
                "persona_name": name,
                "output": res.output,
                "tokens_in": res.tokens_in,
                "tokens_out": res.tokens_out,
                "duration_ms": res.duration_ms,
                "tool_calls": res.tool_calls,
                "tool_call_names": res.tool_call_names,
                "success": res.success,
                "error": res.error,
                "step_kind": "persona",
                "round_num": None,
                "max_rounds": None,
            }
            if i < len(team_result.step_metadata):
                meta = team_result.step_metadata[i]
                entry["step_kind"] = meta.step_kind
                entry["round_num"] = meta.round_num
                entry["max_rounds"] = meta.max_rounds
            step_entries.append(entry)

        cost = None
        if team_model:
            from initrunner.dashboard.pricing import estimate_cost

            cost = estimate_cost(
                team_result.total_tokens_in,
                team_result.total_tokens_out,
                team_model[1],
                team_model[0],
            )

        return {
            "team_run_id": team_result.team_run_id,
            "output": team_result.final_output,
            "steps": step_entries,
            "tokens_in": team_result.total_tokens_in,
            "tokens_out": team_result.total_tokens_out,
            "total_tokens": team_result.total_tokens,
            "duration_ms": team_result.total_duration_ms,
            "success": team_result.success,
            "error": team_result.error,
            "cost": cost,
        }

    async for event in _sse_pump(event_queue, team_task, _build, "Error during team SSE streaming"):
        yield event


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

    async for event in _sse_pump(
        event_queue, ingest_task, _build_ingest_payload, "Error during ingest SSE streaming"
    ):
        yield event


async def stream_team_ingest_sse(
    team: TeamDefinition,
    team_dir: Path,
    *,
    force: bool = False,
) -> AsyncIterator[str]:
    """SSE generator for team shared-document ingestion."""
    from initrunner.agent.schema.ingestion import IngestConfig
    from initrunner.ingestion.pipeline import run_ingest
    from initrunner.stores.base import DEFAULT_STORES_DIR

    loop = asyncio.get_running_loop()
    event_queue: asyncio.Queue[str | None] = asyncio.Queue(maxsize=_TOKEN_QUEUE_MAX)

    store_path = team.spec.shared_documents.store_path or str(
        DEFAULT_STORES_DIR / f"{team.metadata.name}-shared.lance"
    )
    ingest_config = IngestConfig(
        sources=team.spec.shared_documents.sources,
        store_path=store_path,
        store_backend=team.spec.shared_documents.store_backend,
        embeddings=team.spec.shared_documents.embeddings,
        chunking=team.spec.shared_documents.chunking,
    )
    provider = team.spec.model.provider if team.spec.model else ""

    def on_progress(path: Path, status) -> None:
        evt = json.dumps({"type": "progress", "data": {"path": str(path), "status": str(status)}})
        try:
            loop.call_soon_threadsafe(event_queue.put_nowait, f"data: {evt}\n\n")
        except RuntimeError:
            pass

    def run() -> object:
        try:
            return run_ingest(
                ingest_config,
                team.metadata.name,
                provider=provider,
                base_dir=team_dir,
                force=force,
                progress_callback=on_progress,
            )
        finally:
            loop.call_soon_threadsafe(event_queue.put_nowait, None)

    ingest_task = loop.run_in_executor(None, run)

    async for event in _sse_pump(
        event_queue, ingest_task, _build_ingest_payload, "Error during team ingest SSE streaming"
    ):
        yield event
