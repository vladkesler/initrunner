"""MCP server introspection — list tools without requiring LLM API keys."""

from __future__ import annotations

from pathlib import Path

from initrunner._async import run_sync
from initrunner.agent.schema.tools import McpToolConfig


def list_mcp_tools(
    role_path: Path,
    index: int | None = None,
) -> list[tuple[str, str, str]]:
    """List tools from MCP servers configured in a role file.

    Returns a list of ``(server_summary, tool_name, tool_description)`` tuples.
    Uses the FastMCP client directly — does **not** require valid LLM API keys.
    """
    from initrunner.agent.loader import load_role

    role = load_role(role_path)
    mcp_configs = [t for t in role.spec.tools if isinstance(t, McpToolConfig)]

    if not mcp_configs:
        return []

    if index is not None:
        if index < 0 or index >= len(mcp_configs):
            raise ValueError(f"MCP tool index {index} out of range (0..{len(mcp_configs) - 1})")
        mcp_configs = [mcp_configs[index]]

    results: list[tuple[str, str, str]] = []
    for cfg in mcp_configs:
        summary = cfg.summary()
        tools = _list_tools_for_config(cfg, role_path.parent)
        for name, description in tools:
            results.append((summary, name, description))
    return results


def _list_tools_for_config(config: McpToolConfig, role_dir: Path) -> list[tuple[str, str]]:
    """Connect to an MCP server and list its tools. Returns (name, description) pairs."""
    from fastmcp import Client

    from initrunner.mcp._transport import build_transport

    transport = build_transport(config, role_dir)

    async def _fetch() -> list[tuple[str, str]]:
        async with Client(transport=transport) as client:
            mcp_tools = await client.list_tools()
            return [(t.name, t.description or "") for t in mcp_tools]

    return run_sync(_fetch())
