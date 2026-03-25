"""Agent discovery and detail routes."""

from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from initrunner.dashboard.deps import RoleCache, get_role_cache
from initrunner.dashboard.schemas import AgentDetail, AgentSummary, DeleteResponse, ItemSummary

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
    roles = role_cache.all()
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


def _detail_from(role_id: str, discovered) -> AgentDetail:
    """Build an AgentDetail from a DiscoveredRole."""
    if discovered.error or discovered.role is None:
        from initrunner.agent.schema.base import ModelConfig
        from initrunner.agent.schema.guardrails import Guardrails
        from initrunner.agent.schema.output import OutputConfig

        return AgentDetail(
            id=role_id,
            name=discovered.path.stem,
            description="",
            tags=[],
            path=str(discovered.path),
            error=discovered.error,
            model=ModelConfig(name="unknown").model_dump(),
            output=OutputConfig().model_dump(),
            guardrails=Guardrails().model_dump(),
        )
    role = discovered.role
    meta = role.metadata
    spec = role.spec
    return AgentDetail(
        id=role_id,
        name=meta.name,
        description=meta.description or "",
        tags=list(meta.tags or []),
        path=str(discovered.path),
        author=meta.author or "",
        team=meta.team or "",
        version=meta.version or "",
        model=spec.model.model_dump(),
        output=spec.output.model_dump(),
        guardrails=spec.guardrails.model_dump(),
        memory=spec.memory.model_dump() if spec.memory else None,
        ingest=spec.ingest.model_dump() if spec.ingest else None,
        reasoning=spec.reasoning.model_dump() if spec.reasoning else None,
        autonomy=spec.autonomy.model_dump() if spec.autonomy else None,
        tools=[
            ItemSummary(type=t.type, summary=t.summary(), config=t.model_dump(exclude={"type"}))
            for t in spec.tools
        ],
        triggers=[ItemSummary(type=t.type, summary=t.summary()) for t in spec.triggers],
        sinks=[ItemSummary(type=t.type, summary=t.summary()) for t in spec.sinks],
        skills=list(spec.skills),
        features=list(spec.features),
    )


@router.get("/{agent_id}/detail")
async def get_agent_detail(
    agent_id: str,
    role_cache: Annotated[RoleCache, Depends(get_role_cache)],
) -> AgentDetail:
    dr = role_cache.get(agent_id)
    if dr is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    return _detail_from(agent_id, dr)


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


@router.delete("/{agent_id}")
async def delete_agent(
    agent_id: str,
    role_cache: Annotated[RoleCache, Depends(get_role_cache)],
) -> DeleteResponse:
    dr = role_cache.get(agent_id)
    if dr is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    path = dr.path
    try:
        await asyncio.to_thread(path.unlink, True)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Cannot delete file: {exc}") from exc
    role_cache.evict(agent_id)
    return DeleteResponse(id=agent_id, path=str(path))
