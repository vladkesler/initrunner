"""HTML page routes — roles list, role detail, audit log."""

from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse

from initrunner.api._helpers import resolve_role_path

router = APIRouter(tags=["pages"])


def _templates(request: Request):
    return request.app.state.templates


def _registry(request: Request):
    return request.app.state.role_registry


@router.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Redirect root to roles list."""
    from starlette.responses import RedirectResponse

    return RedirectResponse("/roles", status_code=302)


@router.get("/roles", response_class=HTMLResponse)
async def roles_list(
    request: Request,
    q: Annotated[str | None, Query(description="Filter roles by name")] = None,
):
    """Roles listing page."""
    from initrunner.services import role_to_summary

    registry = _registry(request)
    discovered = await asyncio.to_thread(registry.discover)
    roles = [role_to_summary(d.path, d.role, d.error) for d in discovered]

    if q:
        q_lower = q.lower()
        roles = [r for r in roles if q_lower in r.name.lower() or q_lower in r.description.lower()]

    return _templates(request).TemplateResponse(
        request, "roles/list.html", {"roles": roles, "active_page": "roles"}
    )


@router.get("/roles/table", response_class=HTMLResponse)
async def roles_table_fragment(
    request: Request,
    q: Annotated[str | None, Query(description="Filter roles by name")] = None,
):
    """HTMX fragment: filtered roles table body."""
    from initrunner.services import role_to_summary

    registry = _registry(request)
    discovered = await asyncio.to_thread(registry.discover)
    roles = [role_to_summary(d.path, d.role, d.error) for d in discovered]

    if q:
        q_lower = q.lower()
        roles = [r for r in roles if q_lower in r.name.lower() or q_lower in r.description.lower()]

    return _templates(request).TemplateResponse(request, "roles/_table.html", {"roles": roles})


@router.get("/roles/new", response_class=HTMLResponse)
async def role_create_page(request: Request):
    """Role creation page with form builder and AI generation tabs."""
    from initrunner.templates import TOOL_DESCRIPTIONS

    return _templates(request).TemplateResponse(
        request,
        "roles/create.html",
        {
            "active_page": "roles",
            "tool_types": TOOL_DESCRIPTIONS,
        },
    )


@router.get("/roles/{role_id}", response_class=HTMLResponse)
async def role_detail(request: Request, role_id: str):
    """Role detail page."""
    from initrunner.services import role_to_detail

    path = await resolve_role_path(request, role_id)

    from initrunner.agent.loader import RoleLoadError, load_role

    try:
        role = await asyncio.to_thread(load_role, path)
    except RoleLoadError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None

    detail = role_to_detail(path, role)

    return _templates(request).TemplateResponse(
        request, "roles/detail.html", {"role": detail, "active_page": "roles"}
    )


@router.get("/audit", response_class=HTMLResponse)
async def audit_page(
    request: Request,
    agent_name: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 50,
):
    """Audit log page."""
    from initrunner.services import query_audit_sync

    audit_logger = getattr(request.app.state, "audit_logger", None)
    records = await asyncio.to_thread(
        query_audit_sync,
        agent_name=agent_name,
        limit=limit,
        audit_logger=audit_logger,
    )

    return _templates(request).TemplateResponse(
        request,
        "audit/list.html",
        {
            "records": records,
            "agent_name": agent_name or "",
            "limit": limit,
            "active_page": "audit",
        },
    )


@router.get("/audit/table", response_class=HTMLResponse)
async def audit_table_fragment(
    request: Request,
    agent_name: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 50,
):
    """HTMX fragment: filtered audit table body."""
    from initrunner.services import query_audit_sync

    audit_logger = getattr(request.app.state, "audit_logger", None)
    records = await asyncio.to_thread(
        query_audit_sync,
        agent_name=agent_name,
        limit=limit,
        audit_logger=audit_logger,
    )

    return _templates(request).TemplateResponse(request, "audit/_table.html", {"records": records})


@router.get("/audit/{run_id}", response_class=HTMLResponse)
async def audit_detail_fragment(request: Request, run_id: str):
    """HTMX fragment: audit record detail panel."""
    from initrunner.services import query_audit_sync

    audit_logger = getattr(request.app.state, "audit_logger", None)
    records = await asyncio.to_thread(query_audit_sync, limit=500, audit_logger=audit_logger)
    record = next((r for r in records if r.run_id == run_id), None)
    if record is None:
        raise HTTPException(status_code=404, detail="Record not found")

    return _templates(request).TemplateResponse(request, "audit/_detail.html", {"record": record})
