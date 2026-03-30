"""Team shared-memory browsing and consolidation routes."""

from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query  # type: ignore[import-not-found]

from initrunner.dashboard.deps import TeamCache, get_team_cache
from initrunner.dashboard.schemas import MemoryResponse

router = APIRouter(prefix="/api/teams", tags=["team-memory"])


def _resolve_team_memory_role(team_id: str, team_cache: TeamCache):
    """Resolve team_id to a RoleDefinition with shared memory, or raise."""
    from initrunner.team.stores import resolve_team_memory_role

    dt = team_cache.get(team_id)
    if dt is None or dt.team is None:
        raise HTTPException(status_code=404, detail="Team not found")

    role = resolve_team_memory_role(dt.team)
    if role is None:
        raise HTTPException(status_code=400, detail="Team has no shared memory enabled")
    return role


@router.get("/{team_id}/memories")
async def list_memories(
    team_id: str,
    team_cache: Annotated[TeamCache, Depends(get_team_cache)],
    category: str | None = Query(None),
    memory_type: str | None = Query(None),
    limit: int = Query(100, ge=1, le=1000),
) -> list[MemoryResponse]:
    from initrunner.services.memory import list_memories_sync
    from initrunner.stores.base import MemoryType

    role = _resolve_team_memory_role(team_id, team_cache)
    mt = MemoryType(memory_type) if memory_type else None
    memories = await asyncio.to_thread(
        list_memories_sync, role, category=category, limit=limit, memory_type=mt
    )
    return [
        MemoryResponse(
            id=m.id,
            content=m.content,
            category=m.category,
            memory_type=(
                m.memory_type.value if hasattr(m.memory_type, "value") else str(m.memory_type)
            ),
            created_at=m.created_at,
            consolidated_at=m.consolidated_at,
        )
        for m in memories
    ]


@router.post("/{team_id}/memories/consolidate")
async def consolidate_memories(
    team_id: str,
    team_cache: Annotated[TeamCache, Depends(get_team_cache)],
) -> dict[str, int]:
    from initrunner.services.memory import consolidate_memories_sync

    role = _resolve_team_memory_role(team_id, team_cache)
    count = await asyncio.to_thread(consolidate_memories_sync, role, force=True)
    return {"consolidated": count}
