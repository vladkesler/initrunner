"""Ingest HTML page — delegates to existing SSE API endpoint."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

from initrunner.api._helpers import resolve_role_path

router = APIRouter(tags=["ingest-ui"])


@router.get("/roles/{role_id}/ingest", response_class=HTMLResponse)
async def ingest_page(request: Request, role_id: str):
    """Ingestion management page."""
    role_path = await resolve_role_path(request, role_id)

    from initrunner.agent.loader import load_role

    role = await asyncio.to_thread(load_role, role_path)
    if role.spec.ingest is None:
        raise HTTPException(status_code=400, detail="No ingest config in this role")

    # Get sources list
    from initrunner.ingestion.pipeline import resolve_sources

    files, urls = await asyncio.to_thread(
        resolve_sources, role.spec.ingest.sources, base_dir=role_path.parent
    )

    sources = []
    for f in files:
        try:
            size = f.stat().st_size
        except OSError:
            size = 0
        sources.append({"path": str(f), "name": f.name, "size_bytes": size})
    for url in urls:
        sources.append({"path": url, "name": url, "size_bytes": 0})

    return request.app.state.templates.TemplateResponse(
        request,
        "ingest/page.html",
        {
            "role_id": role_id,
            "role_name": role.metadata.name,
            "sources": sources,
            "active_page": "roles",
        },
    )
