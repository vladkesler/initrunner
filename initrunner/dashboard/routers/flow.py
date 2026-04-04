"""Flow discovery, detail, and delegation event routes."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException  # type: ignore[import-not-found]
from starlette.responses import StreamingResponse

from initrunner.dashboard.deps import (
    FlowCache,
    RoleCache,
    _role_id,
    get_flow_cache,
    get_role_cache,
)
from initrunner.dashboard.schemas import (
    DelegateEventResponse,
    DeleteResponse,
    FlowAgentDetail,
    FlowDetail,
    FlowRunRequest,
    FlowStatsResponse,
    FlowSummary,
    FlowYamlSaveRequest,
    FlowYamlSaveResponse,
    HealthCheckDetail,
    RestartDetail,
    SinkDetail,
)

router = APIRouter(prefix="/api/flows", tags=["flows"])


def _summary_from(cid: str, discovered) -> FlowSummary:
    """Build a FlowSummary from a DiscoveredFlow."""
    if discovered.error or discovered.flow is None:
        return FlowSummary(
            id=cid,
            name=discovered.path.stem,
            description="",
            agent_count=0,
            agent_names=[],
            path=str(discovered.path),
            error=discovered.error,
        )
    comp = discovered.flow
    svc_names = list(comp.spec.agents.keys())
    return FlowSummary(
        id=cid,
        name=comp.metadata.name,
        description=comp.metadata.description or "",
        agent_count=len(svc_names),
        agent_names=svc_names,
        path=str(discovered.path),
    )


def _resolve_agent(role_path_str: str, flow_dir: Path, role_cache: RoleCache):
    """Try to match a flow agent role path to a discovered agent."""
    role_path = Path(role_path_str)
    if not role_path.is_absolute():
        role_path = flow_dir / role_path
    resolved = role_path.resolve()
    rid = _role_id(resolved)
    dr = role_cache.get(rid)
    if dr is not None and dr.role is not None:
        return rid, dr.role.metadata.name
    return None, None


def _detail_from(cid: str, discovered, role_cache: RoleCache) -> FlowDetail:
    """Build a FlowDetail with agent cross-references."""
    comp = discovered.flow
    flow_dir = discovered.path.parent

    agents = []
    for svc_name, svc_config in comp.spec.agents.items():
        agent_id, agent_name = _resolve_agent(svc_config.role, flow_dir, role_cache)

        sink_detail = None
        if svc_config.sink:
            raw_target = svc_config.sink.target
            targets = raw_target if isinstance(raw_target, list) else [raw_target]
            sink_detail = SinkDetail(
                summary=svc_config.sink.summary(),
                strategy=svc_config.sink.strategy,
                targets=targets,
                queue_size=svc_config.sink.queue_size,
                timeout_seconds=svc_config.sink.timeout_seconds,
                circuit_breaker_threshold=svc_config.sink.circuit_breaker_threshold,
            )

        agents.append(
            FlowAgentDetail(
                name=svc_name,
                role_path=svc_config.role,
                agent_id=agent_id,
                agent_name=agent_name,
                sink=sink_detail,
                needs=svc_config.needs,
                trigger_summary=(svc_config.trigger.summary() if svc_config.trigger else None),
                restart=RestartDetail(
                    condition=svc_config.restart.condition,
                    max_retries=svc_config.restart.max_retries,
                    delay_seconds=svc_config.restart.delay_seconds,
                ),
                health_check=HealthCheckDetail(
                    interval_seconds=svc_config.health_check.interval_seconds,
                    timeout_seconds=svc_config.health_check.timeout_seconds,
                    retries=svc_config.health_check.retries,
                ),
                environment_count=len(svc_config.environment),
            )
        )

    return FlowDetail(
        id=cid,
        name=comp.metadata.name,
        description=comp.metadata.description or "",
        path=str(discovered.path),
        agents=agents,
        shared_memory_enabled=comp.spec.shared_memory.enabled,
        shared_documents_enabled=comp.spec.shared_documents.enabled,
    )


@router.get("")
async def list_flows(
    flow_cache: Annotated[FlowCache, Depends(get_flow_cache)],
) -> list[FlowSummary]:
    flows = flow_cache.all()
    return [_summary_from(cid, dc) for cid, dc in flows.items()]


@router.get("/{flow_id}")
async def get_flow(
    flow_id: str,
    flow_cache: Annotated[FlowCache, Depends(get_flow_cache)],
    role_cache: Annotated[RoleCache, Depends(get_role_cache)],
) -> FlowDetail:
    dc = flow_cache.get(flow_id)
    if dc is None:
        raise HTTPException(status_code=404, detail="Flow not found")
    if dc.error or dc.flow is None:
        raise HTTPException(status_code=422, detail=dc.error or "Invalid flow file")
    return _detail_from(flow_id, dc, role_cache)


@router.get("/{flow_id}/yaml")
async def get_flow_yaml(
    flow_id: str,
    flow_cache: Annotated[FlowCache, Depends(get_flow_cache)],
) -> dict[str, str]:
    dc = flow_cache.get(flow_id)
    if dc is None:
        raise HTTPException(status_code=404, detail="Flow not found")
    try:
        content = dc.path.read_text(encoding="utf-8")
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Cannot read file: {exc}") from exc
    return {"yaml": content, "path": str(dc.path)}


@router.get("/{flow_id}/events")
async def get_flow_events(
    flow_id: str,
    flow_cache: Annotated[FlowCache, Depends(get_flow_cache)],
    source: str | None = None,
    target: str | None = None,
    status: str | None = None,
    since: str | None = None,
    until: str | None = None,
    limit: int = 200,
) -> list[DelegateEventResponse]:
    dc = flow_cache.get(flow_id)
    if dc is None:
        raise HTTPException(status_code=404, detail="Flow not found")
    if dc.error or dc.flow is None:
        return []

    flow_name = dc.flow.metadata.name
    events = await asyncio.to_thread(
        _query_events,
        flow_name=flow_name,
        source=source,
        target=target,
        status=status,
        since=since,
        until=until,
        limit=limit,
    )
    return events


@router.get("/{flow_id}/stats")
async def get_flow_stats(
    flow_id: str,
    flow_cache: Annotated[FlowCache, Depends(get_flow_cache)],
) -> FlowStatsResponse:
    dc = flow_cache.get(flow_id)
    if dc is None:
        raise HTTPException(status_code=404, detail="Flow not found")
    if dc.error or dc.flow is None:
        return FlowStatsResponse(total_events=0)

    flow_name = dc.flow.metadata.name
    events = await asyncio.to_thread(
        _query_events,
        flow_name=flow_name,
        source=None,
        target=None,
        status=None,
        since=None,
        until=None,
        limit=10_000,
    )
    by_status: dict[str, int] = {}
    for e in events:
        by_status[e.status] = by_status.get(e.status, 0) + 1
    return FlowStatsResponse(total_events=len(events), by_status=by_status)


@router.put("/{flow_id}/yaml")
async def save_flow_yaml(
    flow_id: str,
    req: FlowYamlSaveRequest,
    flow_cache: Annotated[FlowCache, Depends(get_flow_cache)],
) -> FlowYamlSaveResponse:
    dc = flow_cache.get(flow_id)
    if dc is None:
        raise HTTPException(status_code=404, detail="Flow not found")

    from initrunner.dashboard.validation import validate_flow_yaml

    issues = validate_flow_yaml(req.yaml_text)
    errors = [i for i in issues if i.severity == "error"]
    if errors:
        raise HTTPException(
            status_code=422,
            detail=[{"field": i.field, "message": i.message} for i in errors],
        )

    path = dc.path
    try:
        await asyncio.to_thread(path.write_text, req.yaml_text, "utf-8")
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Cannot write file: {exc}") from exc

    # Refresh cache
    flow_cache.refresh_one(flow_id, path)

    return FlowYamlSaveResponse(
        path=str(path),
        valid=True,
        issues=[i.message for i in issues if i.severity == "warning"],
    )


@router.post("/{flow_id}/run/stream")
async def stream_flow_run(
    flow_id: str,
    req: FlowRunRequest,
    flow_cache: Annotated[FlowCache, Depends(get_flow_cache)],
) -> StreamingResponse:
    dc = flow_cache.get(flow_id)
    if dc is None:
        raise HTTPException(status_code=404, detail="Flow not found")
    if dc.error or dc.flow is None:
        raise HTTPException(status_code=422, detail=dc.error or "Invalid flow file")

    message_history = None
    if req.message_history:
        from initrunner.dashboard.routers.runs import _parse_message_history

        message_history = _parse_message_history(req.message_history)

    from initrunner.dashboard.routers.runs import _audit_logger
    from initrunner.dashboard.streaming import stream_flow_run_sse

    return StreamingResponse(
        stream_flow_run_sse(
            dc.flow,
            dc.path.parent,
            req.prompt,
            audit_logger=_audit_logger(),
            message_history=message_history,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _query_events(
    *,
    flow_name: str,
    source: str | None,
    target: str | None,
    status: str | None,
    since: str | None,
    until: str | None,
    limit: int,
) -> list[DelegateEventResponse]:
    from initrunner.services.operations import query_delegate_events_sync

    raw = query_delegate_events_sync(
        compose_name=flow_name,
        source_service=source,
        target_service=target,
        status=status,
        since=since,
        until=until,
        limit=limit,
    )
    return [
        DelegateEventResponse(
            timestamp=e.timestamp,
            source_agent=e.source_service,
            target_agent=e.target_service,
            status=e.status,
            source_run_id=e.source_run_id,
            flow_name=e.compose_name,
            reason=e.reason,
            trace=e.trace,
            payload_preview=e.payload_preview,
        )
        for e in raw
    ]


@router.delete("/{flow_id}")
async def delete_flow(
    flow_id: str,
    flow_cache: Annotated[FlowCache, Depends(get_flow_cache)],
) -> DeleteResponse:
    dc = flow_cache.get(flow_id)
    if dc is None:
        raise HTTPException(status_code=404, detail="Flow not found")
    path = dc.path
    try:
        await asyncio.to_thread(path.unlink, True)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Cannot delete file: {exc}") from exc
    flow_cache.evict(flow_id)
    return DeleteResponse(id=flow_id, path=str(path))
