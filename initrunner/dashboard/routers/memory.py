"""Agent memory and session browsing routes."""

from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query  # type: ignore[import-not-found]

from initrunner.dashboard.deps import RoleCache, get_role_cache
from initrunner.dashboard.schemas import (
    MemoryResponse,
    SessionDetailResponse,
    SessionMessageResponse,
    SessionSummaryResponse,
)

router = APIRouter(prefix="/api/agents", tags=["memory"])


def _resolve_role(agent_id: str, role_cache: RoleCache):
    """Resolve agent_id to a RoleDefinition or raise 404."""
    dr = role_cache.get(agent_id)
    if dr is None or dr.role is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    return dr.role


@router.get("/{agent_id}/memories")
async def list_memories(
    agent_id: str,
    role_cache: Annotated[RoleCache, Depends(get_role_cache)],
    category: str | None = Query(None),
    memory_type: str | None = Query(None),
    limit: int = Query(100, ge=1, le=1000),
) -> list[MemoryResponse]:
    from initrunner.services.memory import list_memories_sync
    from initrunner.stores.base import MemoryType

    role = _resolve_role(agent_id, role_cache)
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


@router.get("/{agent_id}/sessions")
async def list_sessions(
    agent_id: str,
    role_cache: Annotated[RoleCache, Depends(get_role_cache)],
    limit: int = Query(20, ge=1, le=100),
) -> list[SessionSummaryResponse]:
    from initrunner.services.memory import list_sessions_sync

    role = _resolve_role(agent_id, role_cache)
    sessions = await asyncio.to_thread(list_sessions_sync, role, limit=limit)
    return [
        SessionSummaryResponse(
            session_id=s.session_id,
            agent_name=s.agent_name,
            timestamp=s.timestamp,
            message_count=s.message_count,
            preview=s.preview,
        )
        for s in sessions
    ]


@router.get("/{agent_id}/sessions/{session_id}")
async def get_session(
    agent_id: str,
    session_id: str,
    role_cache: Annotated[RoleCache, Depends(get_role_cache)],
    max_messages: int = Query(500, ge=1, le=5000),
) -> SessionDetailResponse:
    from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, UserPromptPart

    from initrunner.agent.prompt import render_content_as_text
    from initrunner.services.memory import load_session_by_id_sync

    role = _resolve_role(agent_id, role_cache)
    messages = await asyncio.to_thread(
        load_session_by_id_sync, role, session_id, max_messages=max_messages
    )
    if messages is None:
        raise HTTPException(status_code=404, detail="Session not found")

    result: list[SessionMessageResponse] = []
    for msg in messages:
        if isinstance(msg, ModelRequest):
            for part in msg.parts:
                if isinstance(part, UserPromptPart):
                    if isinstance(part.content, str):
                        text = part.content
                    elif isinstance(part.content, list):
                        text = " ".join(render_content_as_text(item) for item in part.content)
                    else:
                        text = str(part.content)
                    result.append(SessionMessageResponse(role="user", content=text))
        elif isinstance(msg, ModelResponse):
            for part in msg.parts:
                if isinstance(part, TextPart):
                    result.append(SessionMessageResponse(role="assistant", content=part.content))

    return SessionDetailResponse(session_id=session_id, messages=result)


@router.post("/{agent_id}/memories/consolidate")
async def consolidate_memories(
    agent_id: str,
    role_cache: Annotated[RoleCache, Depends(get_role_cache)],
) -> dict[str, int]:
    from initrunner.services.memory import consolidate_memories_sync

    role = _resolve_role(agent_id, role_cache)
    count = await asyncio.to_thread(consolidate_memories_sync, role, force=True)
    return {"consolidated": count}
