"""MCP server health checking."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from initrunner.agent.schema.security import ToolSandboxConfig
    from initrunner.agent.schema.tools import McpToolConfig

_HEALTHY_THRESHOLD_S = 3.0
_TIMEOUT_S = 5.0

# Module-level TTL cache: server_id -> (result, monotonic timestamp)
_health_cache: dict[str, tuple[McpServerHealth, float]] = {}
_CACHE_TTL_S = 30.0


@dataclass
class McpServerHealth:
    status: str  # "healthy" | "degraded" | "unhealthy"
    latency_ms: int
    tool_count: int
    error: str | None
    checked_at: str  # ISO timestamp


async def _check(
    config: McpToolConfig,
    role_dir: Path | None = None,
    sandbox: ToolSandboxConfig | None = None,
) -> McpServerHealth:
    from fastmcp import Client  # type: ignore[import-not-found]

    from initrunner.mcp._transport import build_transport

    checked_at = datetime.now(UTC).isoformat()
    transport = build_transport(config, role_dir, sandbox=sandbox)

    t0 = time.monotonic()
    try:
        async with Client(transport=transport) as client:
            tools = await asyncio.wait_for(client.list_tools(), timeout=_TIMEOUT_S)
        elapsed = time.monotonic() - t0
        latency_ms = int(elapsed * 1000)
        status = "degraded" if elapsed > _HEALTHY_THRESHOLD_S else "healthy"
        return McpServerHealth(
            status=status,
            latency_ms=latency_ms,
            tool_count=len(tools),
            error=None,
            checked_at=checked_at,
        )
    except Exception as exc:
        elapsed = time.monotonic() - t0
        return McpServerHealth(
            status="unhealthy",
            latency_ms=int(elapsed * 1000),
            tool_count=0,
            error=str(exc),
            checked_at=checked_at,
        )


def check_health_sync(
    config: McpToolConfig,
    role_dir: Path | None = None,
    sandbox: ToolSandboxConfig | None = None,
    *,
    server_id: str = "",
) -> McpServerHealth:
    """Check MCP server health with optional TTL caching.

    When *server_id* is provided, results are cached for 30 seconds.
    """
    if server_id:
        cached = _health_cache.get(server_id)
        if cached is not None:
            result, ts = cached
            if (time.monotonic() - ts) < _CACHE_TTL_S:
                return result

    result = asyncio.run(_check(config, role_dir, sandbox))

    if server_id:
        _health_cache[server_id] = (result, time.monotonic())

    return result
