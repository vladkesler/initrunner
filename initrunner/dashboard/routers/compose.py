"""Compose discovery, detail, and delegation event routes."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from initrunner.dashboard.deps import (
    ComposeCache,
    RoleCache,
    _role_id,
    get_compose_cache,
    get_role_cache,
)
from initrunner.dashboard.schemas import (
    ComposeDetail,
    ComposeServiceDetail,
    ComposeSummary,
    DelegateEventResponse,
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
        services.append(
            ComposeServiceDetail(
                name=svc_name,
                role_path=svc_config.role,
                agent_id=agent_id,
                agent_name=agent_name,
                sink_summary=svc_config.sink.summary() if svc_config.sink else None,
                depends_on=svc_config.depends_on,
                trigger_summary=svc_config.trigger.summary() if svc_config.trigger else None,
                restart_condition=svc_config.restart.condition,
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
