"""Compose discovery, detail, and delegation event routes."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from starlette.responses import StreamingResponse

from initrunner.dashboard.deps import (
    ComposeCache,
    RoleCache,
    _role_id,
    get_compose_cache,
    get_role_cache,
)
from initrunner.dashboard.schemas import (
    ComposeDetail,
    ComposeRunRequest,
    ComposeServiceDetail,
    ComposeStatsResponse,
    ComposeSummary,
    ComposeYamlSaveRequest,
    ComposeYamlSaveResponse,
    DelegateEventResponse,
    HealthCheckDetail,
    RestartDetail,
    SinkDetail,
)

router = APIRouter(prefix="/api/compose", tags=["compose"])


def _summary_from(cid: str, discovered) -> ComposeSummary:
    """Build a ComposeSummary from a DiscoveredCompose."""
    if discovered.error or discovered.compose is None:
        return ComposeSummary(
            id=cid,
            name=discovered.path.stem,
            description="",
            service_count=0,
            service_names=[],
            path=str(discovered.path),
            error=discovered.error,
        )
    comp = discovered.compose
    svc_names = list(comp.spec.services.keys())
    return ComposeSummary(
        id=cid,
        name=comp.metadata.name,
        description=comp.metadata.description or "",
        service_count=len(svc_names),
        service_names=svc_names,
        path=str(discovered.path),
    )


def _resolve_agent(role_path_str: str, compose_dir: Path, role_cache: RoleCache):
    """Try to match a compose service role path to a discovered agent."""
    role_path = Path(role_path_str)
    if not role_path.is_absolute():
        role_path = compose_dir / role_path
    resolved = role_path.resolve()
    rid = _role_id(resolved)
    dr = role_cache.get(rid)
    if dr is not None and dr.role is not None:
        return rid, dr.role.metadata.name
    return None, None


def _detail_from(cid: str, discovered, role_cache: RoleCache) -> ComposeDetail:
    """Build a ComposeDetail with agent cross-references."""
    comp = discovered.compose
    compose_dir = discovered.path.parent

    services = []
    for svc_name, svc_config in comp.spec.services.items():
        agent_id, agent_name = _resolve_agent(svc_config.role, compose_dir, role_cache)

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

        services.append(
            ComposeServiceDetail(
                name=svc_name,
                role_path=svc_config.role,
                agent_id=agent_id,
                agent_name=agent_name,
                sink=sink_detail,
                depends_on=svc_config.depends_on,
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

    return ComposeDetail(
        id=cid,
        name=comp.metadata.name,
        description=comp.metadata.description or "",
        path=str(discovered.path),
        services=services,
        shared_memory_enabled=comp.spec.shared_memory.enabled,
        shared_documents_enabled=comp.spec.shared_documents.enabled,
    )


@router.get("")
async def list_composes(
    compose_cache: Annotated[ComposeCache, Depends(get_compose_cache)],
) -> list[ComposeSummary]:
    composes = compose_cache.all()
    return [_summary_from(cid, dc) for cid, dc in composes.items()]


@router.get("/{compose_id}")
async def get_compose(
    compose_id: str,
    compose_cache: Annotated[ComposeCache, Depends(get_compose_cache)],
    role_cache: Annotated[RoleCache, Depends(get_role_cache)],
) -> ComposeDetail:
    dc = compose_cache.get(compose_id)
    if dc is None:
        raise HTTPException(status_code=404, detail="Compose not found")
    if dc.error or dc.compose is None:
        raise HTTPException(status_code=422, detail=dc.error or "Invalid compose file")
    return _detail_from(compose_id, dc, role_cache)


@router.get("/{compose_id}/yaml")
async def get_compose_yaml(
    compose_id: str,
    compose_cache: Annotated[ComposeCache, Depends(get_compose_cache)],
) -> dict[str, str]:
    dc = compose_cache.get(compose_id)
    if dc is None:
        raise HTTPException(status_code=404, detail="Compose not found")
    try:
        content = dc.path.read_text(encoding="utf-8")
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Cannot read file: {exc}") from exc
    return {"yaml": content, "path": str(dc.path)}


@router.get("/{compose_id}/events")
async def get_compose_events(
    compose_id: str,
    compose_cache: Annotated[ComposeCache, Depends(get_compose_cache)],
    source: str | None = None,
    target: str | None = None,
    status: str | None = None,
    since: str | None = None,
    until: str | None = None,
    limit: int = 200,
) -> list[DelegateEventResponse]:
    dc = compose_cache.get(compose_id)
    if dc is None:
        raise HTTPException(status_code=404, detail="Compose not found")
    if dc.error or dc.compose is None:
        return []

    compose_name = dc.compose.metadata.name
    events = await asyncio.to_thread(
        _query_events,
        compose_name=compose_name,
        source=source,
        target=target,
        status=status,
        since=since,
        until=until,
        limit=limit,
    )
    return events


@router.get("/{compose_id}/stats")
async def get_compose_stats(
    compose_id: str,
    compose_cache: Annotated[ComposeCache, Depends(get_compose_cache)],
) -> ComposeStatsResponse:
    dc = compose_cache.get(compose_id)
    if dc is None:
        raise HTTPException(status_code=404, detail="Compose not found")
    if dc.error or dc.compose is None:
        return ComposeStatsResponse(total_events=0)

    compose_name = dc.compose.metadata.name
    events = await asyncio.to_thread(
        _query_events,
        compose_name=compose_name,
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
    return ComposeStatsResponse(total_events=len(events), by_status=by_status)


@router.put("/{compose_id}/yaml")
async def save_compose_yaml(
    compose_id: str,
    req: ComposeYamlSaveRequest,
    compose_cache: Annotated[ComposeCache, Depends(get_compose_cache)],
) -> ComposeYamlSaveResponse:
    dc = compose_cache.get(compose_id)
    if dc is None:
        raise HTTPException(status_code=404, detail="Compose not found")

    from initrunner.dashboard.validation import validate_compose_yaml

    issues = validate_compose_yaml(req.yaml_text)
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
    compose_cache.refresh_one(compose_id, path)

    return ComposeYamlSaveResponse(
        path=str(path),
        valid=True,
        issues=[i.message for i in issues if i.severity == "warning"],
    )


@router.post("/{compose_id}/run/stream")
async def stream_compose_run(
    compose_id: str,
    req: ComposeRunRequest,
    compose_cache: Annotated[ComposeCache, Depends(get_compose_cache)],
) -> StreamingResponse:
    dc = compose_cache.get(compose_id)
    if dc is None:
        raise HTTPException(status_code=404, detail="Compose not found")
    if dc.error or dc.compose is None:
        raise HTTPException(status_code=422, detail=dc.error or "Invalid compose file")

    message_history = None
    if req.message_history:
        from initrunner.dashboard.routers.runs import _parse_message_history

        message_history = _parse_message_history(req.message_history)

    from initrunner.dashboard.streaming import stream_compose_run_sse

    return StreamingResponse(
        stream_compose_run_sse(
            dc.compose,
            dc.path.parent,
            req.prompt,
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
    compose_name: str,
    source: str | None,
    target: str | None,
    status: str | None,
    since: str | None,
    until: str | None,
    limit: int,
) -> list[DelegateEventResponse]:
    from initrunner.services.operations import query_delegate_events_sync

    raw = query_delegate_events_sync(
        compose_name=compose_name,
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
            source_service=e.source_service,
            target_service=e.target_service,
            status=e.status,
            source_run_id=e.source_run_id,
            compose_name=e.compose_name,
            reason=e.reason,
            trace=e.trace,
            payload_preview=e.payload_preview,
        )
        for e in raw
    ]
