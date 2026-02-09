"""Memory CRUD + export endpoints."""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Query, Request
from fastapi.responses import Response

from initrunner.api._helpers import load_role_with_memory
from initrunner.api.models import MemoryItemResponse, MemoryListResponse

router = APIRouter(prefix="/api/memories", tags=["memory"])


@router.get("/{role_id}", response_model=MemoryListResponse)
async def list_memories(
    role_id: str,
    request: Request,
    category: str | None = Query(None),
    limit: int = Query(100, ge=1, le=1000),
):
    """List memories for a role."""
    role = (await load_role_with_memory(role_id, request))[0]

    from initrunner.services import list_memories_sync

    memories = await asyncio.to_thread(list_memories_sync, role, category=category, limit=limit)

    return MemoryListResponse(
        memories=[
            MemoryItemResponse(
                id=str(m.id),
                content=m.content,
                category=m.category or "",
                created_at=m.created_at,
            )
            for m in memories
        ]
    )


@router.delete("/{role_id}")
async def clear_memories(role_id: str, request: Request):
    """Clear all memories for a role."""
    role = (await load_role_with_memory(role_id, request))[0]

    from initrunner.services import clear_memories_sync

    await asyncio.to_thread(clear_memories_sync, role)
    return {"status": "ok"}


@router.get("/{role_id}/export")
async def export_memories(role_id: str, request: Request):
    """Export memories as a downloadable JSON file."""
    role = (await load_role_with_memory(role_id, request))[0]

    from initrunner.services import export_memories_sync

    data = await asyncio.to_thread(export_memories_sync, role)
    content = json.dumps(data, indent=2)

    return Response(
        content=content,
        media_type="application/json",
        headers={
            "Content-Disposition": f"attachment; filename={role.metadata.name}-memories.json",
        },
    )
