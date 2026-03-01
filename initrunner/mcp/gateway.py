"""MCP gateway — expose InitRunner agents as MCP tools."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from fastmcp import FastMCP

if TYPE_CHECKING:
    from pydantic_ai import Agent

    from initrunner.agent.schema.role import RoleDefinition
    from initrunner.agent.schema.tools import McpToolConfig
    from initrunner.audit.logger import AuditLogger


@dataclass
class _AgentEntry:
    name: str
    description: str
    role: RoleDefinition
    agent: Agent
    role_path: Path


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_VALID_TOOL_NAME = re.compile(r"^[a-zA-Z0-9_-]+$")


def _sanitize_name(name: str) -> str:
    """Replace characters that are not valid in MCP tool names."""
    return re.sub(r"[^a-zA-Z0-9_-]", "_", name)


def _make_tool_name(name: str, seen: set[str]) -> str:
    """Derive a unique, MCP-valid tool name from a role name."""
    base = _sanitize_name(name)
    if not base:
        base = "agent"
    candidate = base
    counter = 2
    while candidate in seen:
        candidate = f"{base}_{counter}"
        counter += 1
    seen.add(candidate)
    return candidate


def _load_agents(
    role_paths: list[Path],
    extra_skill_dirs: list[Path] | None = None,
) -> list[_AgentEntry]:
    """Load and build agents for each role path. Fails fast on errors."""
    from initrunner.agent.loader import load_and_build

    entries: list[_AgentEntry] = []
    for role_path in role_paths:
        try:
            role, agent = load_and_build(role_path, extra_skill_dirs=extra_skill_dirs)
        except Exception as e:
            raise RuntimeError(f"Failed to load {role_path}: {e}") from e
        entries.append(
            _AgentEntry(
                name=role.metadata.name,
                description=role.metadata.description or f"Agent: {role.metadata.name}",
                role=role,
                agent=agent,
                role_path=role_path,
            )
        )
    return entries


def _register_agent_tool(
    mcp: FastMCP,
    entry: _AgentEntry,
    tool_name: str,
    audit_logger: AuditLogger | None,
) -> None:
    """Register a single agent as an MCP tool using a factory to capture closures."""
    from initrunner.agent.executor import execute_run

    def handler(prompt: str) -> str:
        try:
            result, _ = execute_run(entry.agent, entry.role, prompt, audit_logger=audit_logger)
            if not result.success:
                return f"Error: {result.error}"
            return result.output
        except Exception as e:
            return f"Internal error: {e}"

    handler.__name__ = tool_name.replace("-", "_")
    handler.__doc__ = entry.description
    mcp.tool(handler, name=tool_name, description=entry.description)


def _build_pass_through_transport(
    config: McpToolConfig,
    role: RoleDefinition,
    role_dir: Path,
):
    """Build a transport for pass-through with full sandbox checks (mirrors server.py)."""
    from initrunner.agent._env import resolve_env_vars
    from initrunner.agent._subprocess import scrub_env

    sandbox = role.spec.security.tools

    if config.transport == "stdio":
        from fastmcp.client.transports import StdioTransport

        # Validate MCP command against allowlist
        if sandbox.mcp_command_allowlist and config.command:
            if config.command not in sandbox.mcp_command_allowlist:
                raise ValueError(
                    f"MCP command '{config.command}' is not in the allowed command list: "
                    f"{sandbox.mcp_command_allowlist}"
                )

        kwargs: dict = {"command": config.command, "args": config.args}

        # Build env: scrubbed system env + interpolated config env
        base_env = scrub_env(
            sandbox.sensitive_env_prefixes,
            suffixes=sandbox.sensitive_env_suffixes,
            allowlist=set(sandbox.env_allowlist),
        )
        resolved_env = {k: resolve_env_vars(v) for k, v in config.env.items()}
        kwargs["env"] = {**base_env, **resolved_env}

        # Resolve cwd relative to role dir if provided
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

        resolved_headers = {k: resolve_env_vars(v) for k, v in config.headers.items()}
        sse_kwargs: dict = {"url": config.url}
        if resolved_headers:
            sse_kwargs["headers"] = resolved_headers
        if config.timeout is not None:
            sse_kwargs["timeout"] = config.timeout
        return SSETransport(**sse_kwargs)

    else:
        from fastmcp.client.transports import StreamableHttpTransport

        resolved_headers = {k: resolve_env_vars(v) for k, v in config.headers.items()}
        http_kwargs: dict = {"url": config.url}
        if resolved_headers:
            http_kwargs["headers"] = resolved_headers
        if config.timeout is not None:
            http_kwargs["timeout"] = config.timeout
        return StreamableHttpTransport(**http_kwargs)


def _register_pass_through_tools(
    mcp: FastMCP,
    entries: list[_AgentEntry],
) -> None:
    """Mount pass-through proxies for MCP tools configured on each agent."""
    from initrunner.agent.schema.tools import McpToolConfig

    for entry in entries:
        mcp_configs = [t for t in entry.role.spec.tools if isinstance(t, McpToolConfig)]
        if not mcp_configs:
            continue

        agent_prefix = _sanitize_name(entry.name) + "_"

        for cfg in mcp_configs:
            transport = _build_pass_through_transport(cfg, entry.role, entry.role_path.parent)
            proxy = FastMCP.as_proxy(transport)

            # Build the combined prefix: agent_name_ + optional tool_prefix from config
            prefix = agent_prefix
            if cfg.tool_prefix:
                prefix += cfg.tool_prefix

            # Apply tool_filter / tool_exclude on the proxy
            if cfg.tool_filter:
                allowed = set(cfg.tool_filter)
                proxy = proxy.filtered(  # type: ignore[unresolved-attribute]
                    lambda _ctx, tool_def, _a=allowed: tool_def.name in _a
                )
            elif cfg.tool_exclude:
                excluded = set(cfg.tool_exclude)
                proxy = proxy.filtered(  # type: ignore[unresolved-attribute]
                    lambda _ctx, tool_def, _e=excluded: tool_def.name not in _e
                )

            proxy = proxy.prefixed(prefix)  # type: ignore[possibly-missing-attribute]
            mcp.mount(proxy)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_mcp_gateway(
    role_paths: list[Path],
    *,
    server_name: str = "initrunner",
    audit_logger: AuditLogger | None = None,
    pass_through: bool = False,
    extra_skill_dirs: list[Path] | None = None,
) -> FastMCP:
    """Build a FastMCP server that exposes InitRunner agents as MCP tools."""
    if not role_paths:
        raise ValueError("At least one role file required")

    entries = _load_agents(role_paths, extra_skill_dirs)
    mcp = FastMCP(server_name)

    seen: set[str] = set()
    for entry in entries:
        tool_name = _make_tool_name(entry.name, seen)
        _register_agent_tool(mcp, entry, tool_name, audit_logger)

    if pass_through:
        _register_pass_through_tools(mcp, entries)

    return mcp


_VALID_TRANSPORTS = {"stdio", "sse", "streamable-http"}


def run_mcp_gateway(
    mcp: FastMCP,
    transport: str = "stdio",
    host: str = "127.0.0.1",
    port: int = 8080,
) -> None:
    """Run an MCP gateway server with the specified transport."""
    if transport not in _VALID_TRANSPORTS:
        raise ValueError(f"Unknown transport: {transport!r}. Expected: stdio, sse, streamable-http")

    if transport == "stdio":
        mcp.run(transport="stdio", show_banner=False)
    elif transport == "sse":
        mcp.run(transport="sse", host=host, port=port)
    else:
        mcp.run(transport="streamable-http", host=host, port=port)
