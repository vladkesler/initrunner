"""Daemon HTML page — delegates to existing WebSocket API endpoint."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

from initrunner.api._helpers import resolve_role_path

router = APIRouter(tags=["daemon-ui"])


@router.get("/roles/{role_id}/daemon", response_class=HTMLResponse)
async def daemon_page(request: Request, role_id: str):
    """Daemon control page."""
    role_path = await resolve_role_path(request, role_id)

    from initrunner.agent.loader import load_role

    role = await asyncio.to_thread(load_role, role_path)
    if not role.spec.triggers:
        raise HTTPException(status_code=400, detail="No triggers configured")

    triggers = [{"type": t.type, "summary": t.summary()} for t in role.spec.triggers]

    return request.app.state.templates.TemplateResponse(
        request,
        "daemon/page.html",
        {
            "role_id": role_id,
            "role_name": role.metadata.name,
            "triggers": triggers,
            "active_page": "roles",
        },
    )
