"""Agent execution routes -- single run and streaming."""

from __future__ import annotations

import asyncio
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException  # type: ignore[import-not-found]
from fastapi.responses import StreamingResponse  # type: ignore[import-not-found]

from initrunner.dashboard.deps import RoleCache, get_role_cache
from initrunner.dashboard.schemas import RunRequest, RunResponse

router = APIRouter(prefix="/api/runs", tags=["runs"])

_logger = logging.getLogger(__name__)


def _audit_logger():
    """Create an AuditLogger writing to the default audit DB."""
    from initrunner.audit.logger import AuditLogger
    from initrunner.config import get_audit_db_path

    return AuditLogger(get_audit_db_path())


def _parse_message_history(raw: str | None):
    """Deserialize an opaque message_history JSON string.

    Returns ``list[ModelMessage]`` or ``None``.
    Raises :class:`HTTPException` 400 on malformed input.
    """
    if raw is None:
        return None
    from pydantic_ai.messages import ModelMessagesTypeAdapter

    try:
        return list(ModelMessagesTypeAdapter.validate_json(raw))
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid message_history: {exc}",
        ) from exc


def _serialize_history(role, messages):
    """Trim and serialize a message list for the response."""
    from pydantic_ai.messages import ModelMessagesTypeAdapter

    from initrunner.agent.history import session_limits, trim_message_history

    _, max_history = session_limits(role)
    trimmed = trim_message_history(messages, max_history)
    return ModelMessagesTypeAdapter.dump_json(trimmed).decode("utf-8")


@router.post("")
async def execute_run(
    req: RunRequest,
    role_cache: Annotated[RoleCache, Depends(get_role_cache)],
) -> RunResponse:
    dr = role_cache.get(req.agent_id)
    if dr is None:
        raise HTTPException(status_code=404, detail="Agent not found")

    history = _parse_message_history(req.message_history)

    from initrunner.services.execution import build_agent_sync, execute_run_sync

    role, agent = await asyncio.to_thread(
        build_agent_sync, dr.path, model_override=req.model_override
    )
    result, new_messages = await asyncio.to_thread(
        execute_run_sync,
        agent,
        role,
        req.prompt,
        audit_logger=_audit_logger(),
        message_history=history,
    )
    return RunResponse(
        run_id=result.run_id,
        output=result.output,
        tokens_in=result.tokens_in,
        tokens_out=result.tokens_out,
        total_tokens=result.total_tokens,
        tool_calls=result.tool_calls,
        tool_call_names=result.tool_call_names,
        duration_ms=result.duration_ms,
        success=result.success,
        error=result.error,
        message_history=_serialize_history(role, new_messages) if result.success else None,
    )


@router.post("/stream")
async def stream_run(
    req: RunRequest,
    role_cache: Annotated[RoleCache, Depends(get_role_cache)],
) -> StreamingResponse:
    dr = role_cache.get(req.agent_id)
    if dr is None:
        raise HTTPException(status_code=404, detail="Agent not found")

    history = _parse_message_history(req.message_history)

    from initrunner.dashboard.streaming import stream_run_sse

    return StreamingResponse(
        stream_run_sse(
            dr.path,
            req.prompt,
            model_override=req.model_override,
            audit_logger=_audit_logger(),
            message_history=history,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
