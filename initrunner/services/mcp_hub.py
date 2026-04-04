"""MCP Hub service -- aggregate, introspect, health-check, and execute MCP servers."""

from __future__ import annotations

import asyncio
import hashlib
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from initrunner.agent.schema.security import ToolSandboxConfig
    from initrunner.agent.schema.tools import McpToolConfig
    from initrunner.dashboard.deps import RoleCache

_logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class AgentRef:
    agent_name: str
    agent_id: str
    role_path: str
    tool_filter: list[str] = field(default_factory=list)
    tool_exclude: list[str] = field(default_factory=list)
    tool_prefix: str | None = None


@dataclass
class McpServerEntry:
    server_id: str
    display_name: str
    transport: str
    command: str | None
    args: list[str]
    url: str | None
    agent_refs: list[AgentRef]
    config: McpToolConfig
    role_dir: Path | None
    sandbox: ToolSandboxConfig | None


@dataclass
class McpToolInfo:
    name: str
    description: str
    input_schema: dict


# ---------------------------------------------------------------------------
# Identity hashing
# ---------------------------------------------------------------------------


def _server_identity_hash(config: McpToolConfig) -> str:
    """Deterministic 12-char hash from connection-relevant config fields."""
    parts = [
        config.transport,
        config.command or "",
        str(sorted(config.args)),
        config.url or "",
        config.cwd or "",
        str(sorted(config.headers.items())),
        str(sorted(config.env.keys())),
    ]
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:12]


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


def aggregate_mcp_servers(role_cache: RoleCache) -> list[McpServerEntry]:
    """Scan all roles and return deduplicated MCP server entries."""
    from initrunner.agent.schema.tools import McpToolConfig

    servers: dict[str, McpServerEntry] = {}

    for role_id, discovered in role_cache.all().items():
        if discovered.error or discovered.role is None:
            continue

        role = discovered.role
        role_dir = discovered.path.parent
        sandbox = role.spec.security.tools
        agent_name = role.metadata.name

        for tool_cfg in role.spec.tools:
            if not isinstance(tool_cfg, McpToolConfig):
                continue

            sid = _server_identity_hash(tool_cfg)
            ref = AgentRef(
                agent_name=agent_name,
                agent_id=role_id,
                role_path=str(discovered.path),
                tool_filter=list(tool_cfg.tool_filter),
                tool_exclude=list(tool_cfg.tool_exclude),
                tool_prefix=tool_cfg.tool_prefix,
            )

            if sid in servers:
                servers[sid].agent_refs.append(ref)
            else:
                servers[sid] = McpServerEntry(
                    server_id=sid,
                    display_name=tool_cfg.summary(),
                    transport=tool_cfg.transport,
                    command=tool_cfg.command,
                    args=list(tool_cfg.args),
                    url=tool_cfg.url,
                    agent_refs=[ref],
                    config=tool_cfg,
                    role_dir=role_dir,
                    sandbox=sandbox,
                )

    return list(servers.values())


def find_server(server_id: str, role_cache: RoleCache) -> McpServerEntry | None:
    """Resolve a server_id back to its entry."""
    for entry in aggregate_mcp_servers(role_cache):
        if entry.server_id == server_id:
            return entry
    return None


# ---------------------------------------------------------------------------
# Introspection (extends introspect.py with inputSchema)
# ---------------------------------------------------------------------------


def introspect_server_sync(
    config: McpToolConfig,
    role_dir: Path | None = None,
    sandbox: ToolSandboxConfig | None = None,
) -> list[McpToolInfo]:
    """List tools with full input schemas from an MCP server."""
    from fastmcp import Client  # type: ignore[import-not-found]

    from initrunner.mcp._transport import build_transport

    transport = build_transport(config, role_dir, sandbox=sandbox)

    async def _fetch() -> list[McpToolInfo]:
        async with Client(transport=transport) as client:
            mcp_tools = await client.list_tools()
            return [
                McpToolInfo(
                    name=t.name,
                    description=t.description or "",
                    input_schema=t.inputSchema if hasattr(t, "inputSchema") else {},
                )
                for t in mcp_tools
            ]

    return asyncio.run(_fetch())
