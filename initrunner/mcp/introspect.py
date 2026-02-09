"""MCP server introspection — list tools without requiring LLM API keys."""

from __future__ import annotations

import asyncio
from pathlib import Path

from initrunner.agent.schema import McpToolConfig


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

    transport = _build_transport(config, role_dir)

    async def _fetch() -> list[tuple[str, str]]:
        async with Client(transport=transport) as client:
            mcp_tools = await client.list_tools()
            return [(t.name, t.description or "") for t in mcp_tools]

    return asyncio.run(_fetch())


def _build_transport(config: McpToolConfig, role_dir: Path):
    """Build a transport for introspection (lightweight, no sandbox checks)."""
    from initrunner.agent._env import resolve_env_vars
    from initrunner.agent._subprocess import scrub_env

    if config.transport == "stdio":
        from fastmcp.client.transports import StdioTransport

        kwargs: dict = {"command": config.command, "args": config.args}
        base_env = scrub_env()
        resolved_env = {k: resolve_env_vars(v) for k, v in config.env.items()}
        kwargs["env"] = {**base_env, **resolved_env}
        if config.cwd is not None:
            cwd_path = Path(config.cwd)
            if not cwd_path.is_absolute():
                cwd_path = role_dir / cwd_path
            kwargs["cwd"] = str(cwd_path)
        if config.timeout is not None:
            kwargs["timeout"] = config.timeout
        return StdioTransport(**kwargs)
    elif config.transport == "sse":
        from fastmcp.client.transports import SSETransport

        sse_kwargs: dict = {"url": config.url}
        resolved_headers = {k: resolve_env_vars(v) for k, v in config.headers.items()}
        if resolved_headers:
            sse_kwargs["headers"] = resolved_headers
        if config.timeout is not None:
            sse_kwargs["timeout"] = config.timeout
        return SSETransport(**sse_kwargs)
    else:
        from fastmcp.client.transports import StreamableHttpTransport

        http_kwargs: dict = {"url": config.url}
        resolved_headers = {k: resolve_env_vars(v) for k, v in config.headers.items()}
        if resolved_headers:
            http_kwargs["headers"] = resolved_headers
        if config.timeout is not None:
            http_kwargs["timeout"] = config.timeout
        return StreamableHttpTransport(**http_kwargs)
