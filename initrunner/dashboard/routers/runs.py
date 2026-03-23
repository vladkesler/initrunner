"""Agent execution routes -- single run and streaming."""

from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from initrunner.dashboard.deps import RoleCache, get_role_cache
from initrunner.dashboard.schemas import RunRequest, RunResponse

router = APIRouter(prefix="/api/runs", tags=["runs"])


@router.post("")
async def execute_run(
    req: RunRequest,
    role_cache: Annotated[RoleCache, Depends(get_role_cache)],
) -> RunResponse:
    dr = role_cache.get(req.agent_id)
    if dr is None:
        raise HTTPException(status_code=404, detail="Agent not found")

    from initrunner.services.execution import build_agent_sync, execute_run_sync

    role, agent = await asyncio.to_thread(
        build_agent_sync, dr.path, model_override=req.model_override
    )
    result, _ = await asyncio.to_thread(execute_run_sync, agent, role, req.prompt)
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
    )


@router.post("/stream")
async def stream_run(
    req: RunRequest,
    role_cache: Annotated[RoleCache, Depends(get_role_cache)],
) -> StreamingResponse:
    dr = role_cache.get(req.agent_id)
    if dr is None:
        raise HTTPException(status_code=404, detail="Agent not found")

    from initrunner.dashboard.streaming import stream_run_sse

    return StreamingResponse(
        stream_run_sse(dr.path, req.prompt, model_override=req.model_override),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
