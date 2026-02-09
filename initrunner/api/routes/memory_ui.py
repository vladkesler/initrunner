"""Memory HTML page + HTMX fragments."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse

from initrunner.api._helpers import load_role_with_memory

router = APIRouter(tags=["memory-ui"])


@router.get("/roles/{role_id}/memory", response_class=HTMLResponse)
async def memory_page(request: Request, role_id: str):
    """Memory management page."""
    role, _path = await load_role_with_memory(role_id, request)

    from initrunner.services import list_memories_sync

    memories = await asyncio.to_thread(list_memories_sync, role, limit=100)

    return request.app.state.templates.TemplateResponse(
        request,
        "memory/page.html",
        {
            "role_id": role_id,
            "role_name": role.metadata.name,
            "memories": [
                {
                    "id": str(m.id),
                    "content": m.content,
                    "category": m.category or "",
                    "created_at": m.created_at,
                }
                for m in memories
            ],
            "active_page": "roles",
        },
    )


@router.get("/roles/{role_id}/memory/table", response_class=HTMLResponse)
async def memory_table_fragment(
    request: Request,
    role_id: str,
    category: str | None = Query(None),
):
    """HTMX fragment: filtered memory table body."""
    role, _path = await load_role_with_memory(role_id, request)

    from initrunner.services import list_memories_sync

    memories = await asyncio.to_thread(
        list_memories_sync, role, category=category if category else None, limit=100
    )

    rows = []
    for m in memories:
        content = m.content
        truncated = content[:200] + "..." if len(content) > 200 else content
        cat = m.category or "—"
        created = m.created_at[:19]
        rows.append(
            f'<tr><td class="text-xs mono whitespace-nowrap">{created}</td>'
            f'<td><span class="badge badge-ghost badge-sm">{cat}</span></td>'
            f'<td class="text-sm">{truncated}</td></tr>'
        )

    if not rows:
        return HTMLResponse(
            '<tr><td colspan="3" class="text-center text-base-content/50 py-8">'
            "No memories found</td></tr>"
        )
    return HTMLResponse("\n".join(rows))


@router.delete("/roles/{role_id}/memory/clear", response_class=HTMLResponse)
async def memory_clear(request: Request, role_id: str):
    """HTMX action: clear all memories, return empty table body."""
    role, _path = await load_role_with_memory(role_id, request)

    from initrunner.services import clear_memories_sync

    await asyncio.to_thread(clear_memories_sync, role)

    return HTMLResponse(
        '<tr><td colspan="3" class="text-center text-base-content/50 py-8">'
        "All memories cleared</td></tr>"
    )
