"""Agent discovery and detail routes."""

from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from initrunner.dashboard.deps import RoleCache, get_role_cache
from initrunner.dashboard.schemas import AgentSummary

router = APIRouter(prefix="/api/agents", tags=["agents"])


def _summary_from(role_id: str, discovered) -> AgentSummary:
    """Build an AgentSummary from a DiscoveredRole."""
    if discovered.error or discovered.role is None:
        return AgentSummary(
            id=role_id,
            name=discovered.path.stem,
            description="",
            tags=[],
            provider="",
            model="",
            features=[],
            path=str(discovered.path),
            error=discovered.error,
        )
    role = discovered.role
    meta = role.metadata
    spec = role.spec
    return AgentSummary(
        id=role_id,
        name=meta.name,
        description=meta.description or "",
        tags=list(meta.tags or []),
        provider=spec.model.provider if spec.model else "",
        model=spec.model.name if spec.model else "",
        features=list(spec.features),
        path=str(discovered.path),
    )


@router.get("")
async def list_agents(
    role_cache: Annotated[RoleCache, Depends(get_role_cache)],
) -> list[AgentSummary]:
    roles = await asyncio.to_thread(role_cache.refresh)
    return [_summary_from(rid, dr) for rid, dr in roles.items()]


@router.get("/{agent_id}")
async def get_agent(
    agent_id: str,
    role_cache: Annotated[RoleCache, Depends(get_role_cache)],
) -> AgentSummary:
    dr = role_cache.get(agent_id)
    if dr is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    return _summary_from(agent_id, dr)


@router.get("/{agent_id}/yaml")
async def get_agent_yaml(
    agent_id: str,
    role_cache: Annotated[RoleCache, Depends(get_role_cache)],
) -> dict[str, str]:
    dr = role_cache.get(agent_id)
    if dr is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    try:
        content = dr.path.read_text(encoding="utf-8")
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Cannot read file: {exc}") from exc
    return {"yaml": content, "path": str(dr.path)}
