"""MCP Hub API routes -- server discovery, introspection, health, and playground."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException  # type: ignore[import-not-found]

from initrunner.dashboard.deps import RoleCache, get_role_cache
from initrunner.dashboard.schemas import (
    McpAgentRefResponse,
    McpHealthResponse,
    McpHealthSummaryResponse,
    McpPlaygroundRequest,
    McpPlaygroundResponse,
    McpRegistryEntryResponse,
    McpServerResponse,
    McpToolResponse,
)

_logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/mcp", tags=["mcp"])

_REGISTRY_PATH = (
    Path(__file__).resolve().parent.parent.parent / "mcp" / "_registry_data" / "catalog.json"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _entry_to_response(entry) -> McpServerResponse:
    from initrunner.mcp.health import _health_cache

    health_status: str | None = None
    health_checked_at: str | None = None
    cached = _health_cache.get(entry.server_id)
    if cached is not None:
        result, _ts = cached
        health_status = result.status
        health_checked_at = result.checked_at

    return McpServerResponse(
        server_id=entry.server_id,
        display_name=entry.display_name,
        transport=entry.transport,
        command=entry.command,
        args=entry.args,
        url=entry.url,
        agent_refs=[
            McpAgentRefResponse(
                agent_name=r.agent_name,
                agent_id=r.agent_id,
                role_path=r.role_path,
                tool_filter=r.tool_filter,
                tool_exclude=r.tool_exclude,
                tool_prefix=r.tool_prefix,
            )
            for r in entry.agent_refs
        ],
        health_status=health_status,
        health_checked_at=health_checked_at,
    )


def _find_or_404(server_id: str, role_cache: RoleCache):
    from initrunner.services.mcp_hub import find_server

    entry = find_server(server_id, role_cache)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"MCP server {server_id!r} not found")
    return entry


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/servers")
async def list_servers(
    role_cache: Annotated[RoleCache, Depends(get_role_cache)],
) -> list[McpServerResponse]:
    from initrunner.services.mcp_hub import aggregate_mcp_servers

    entries = await asyncio.to_thread(aggregate_mcp_servers, role_cache)
    return [_entry_to_response(e) for e in entries]


@router.get("/servers/{server_id}/tools")
async def list_server_tools(
    server_id: str,
    role_cache: Annotated[RoleCache, Depends(get_role_cache)],
) -> list[McpToolResponse]:
    from initrunner.services.mcp_hub import introspect_server_sync

    entry = await asyncio.to_thread(_find_or_404, server_id, role_cache)
    try:
        tools = await asyncio.to_thread(
            introspect_server_sync, entry.config, entry.role_dir, entry.sandbox
        )
    except Exception as exc:
        _logger.warning("Failed to introspect MCP server %s: %s", server_id, exc)
        raise HTTPException(
            status_code=502, detail=f"Failed to connect to MCP server: {exc}"
        ) from None
    return [
        McpToolResponse(name=t.name, description=t.description, input_schema=t.input_schema)
        for t in tools
    ]


@router.post("/servers/{server_id}/health")
async def check_server_health(
    server_id: str,
    role_cache: Annotated[RoleCache, Depends(get_role_cache)],
) -> McpHealthResponse:
    from initrunner.mcp.health import check_health_sync

    entry = await asyncio.to_thread(_find_or_404, server_id, role_cache)
    result = await asyncio.to_thread(
        check_health_sync, entry.config, entry.role_dir, entry.sandbox, server_id=server_id
    )
    return McpHealthResponse(
        server_id=server_id,
        status=result.status,
        latency_ms=result.latency_ms,
        tool_count=result.tool_count,
        error=result.error,
        checked_at=result.checked_at,
    )


@router.post("/playground/call")
async def playground_call(
    req: McpPlaygroundRequest,
    role_cache: Annotated[RoleCache, Depends(get_role_cache)],
) -> McpPlaygroundResponse:
    from initrunner.mcp.playground import execute_tool_sync

    entry = await asyncio.to_thread(_find_or_404, req.server_id, role_cache)
    result = await asyncio.to_thread(
        execute_tool_sync,
        entry.config,
        req.tool_name,
        req.arguments,
        entry.role_dir,
        entry.sandbox,
    )
    return McpPlaygroundResponse(
        tool_name=result.tool_name,
        output=result.output,
        duration_ms=result.duration_ms,
        success=result.success,
        error=result.error,
    )


@router.get("/registry")
async def get_registry() -> list[McpRegistryEntryResponse]:
    def _load() -> list[dict[str, Any]]:
        with open(_REGISTRY_PATH) as f:
            return json.load(f)

    entries = await asyncio.to_thread(_load)
    return [McpRegistryEntryResponse(**e) for e in entries]


@router.get("/health-summary")
async def health_summary(
    role_cache: Annotated[RoleCache, Depends(get_role_cache)],
) -> McpHealthSummaryResponse:
    from initrunner.mcp.health import _health_cache
    from initrunner.services.mcp_hub import aggregate_mcp_servers

    entries = await asyncio.to_thread(aggregate_mcp_servers, role_cache)
    total = len(entries)
    healthy = 0
    unhealthy = 0
    for entry in entries:
        cached = _health_cache.get(entry.server_id)
        if cached is not None:
            result, _ts = cached
            if result.status == "unhealthy":
                unhealthy += 1
            else:
                healthy += 1
    return McpHealthSummaryResponse(total=total, healthy=healthy, unhealthy=unhealthy)
