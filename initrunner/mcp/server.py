"""FastMCPToolset wrapper for McpToolConfig."""

from __future__ import annotations

from pathlib import Path

from pydantic_ai.toolsets.abstract import AbstractToolset
from pydantic_ai.toolsets.fastmcp import FastMCPToolset

from initrunner.agent._env import resolve_env_vars
from initrunner.agent._subprocess import scrub_env
from initrunner.agent.schema.tools import McpToolConfig
from initrunner.agent.tools._registry import ToolBuildContext, register_tool


@register_tool("mcp", McpToolConfig)
def build_mcp_toolset(
    config: McpToolConfig,
    ctx: ToolBuildContext,
) -> AbstractToolset:
    """Build a FastMCPToolset from an McpToolConfig."""
    sandbox = ctx.role.spec.security.tools

    # Validate MCP command against allowlist
    if sandbox.mcp_command_allowlist and config.transport == "stdio" and config.command:
        if config.command not in sandbox.mcp_command_allowlist:
            raise ValueError(
                f"MCP command '{config.command}' is not in the allowed command list: "
                f"{sandbox.mcp_command_allowlist}"
            )

    # Interpolate env vars in headers
    resolved_headers = {k: resolve_env_vars(v) for k, v in config.headers.items()}

    if config.transport == "stdio":
        from fastmcp.client.transports import StdioTransport

        kwargs: dict = {"command": config.command, "args": config.args}

        # Build env: scrubbed system env + interpolated config env
        base_env = scrub_env(
            sandbox.sensitive_env_prefixes,
            suffixes=sandbox.sensitive_env_suffixes,
            allowlist=set(sandbox.env_allowlist),
        )
        resolved_env = {k: resolve_env_vars(v) for k, v in config.env.items()}
        kwargs["env"] = {**base_env, **resolved_env}

        # Resolve cwd relative to role_dir if provided
        if config.cwd is not None:
            cwd_path = Path(config.cwd)
            if not cwd_path.is_absolute() and ctx.role_dir is not None:
                cwd_path = ctx.role_dir / cwd_path
            kwargs["cwd"] = str(cwd_path)

        if config.timeout is not None:
            kwargs["timeout"] = config.timeout

        toolset = FastMCPToolset(StdioTransport(**kwargs), max_retries=config.max_retries)
    elif config.transport == "sse":
        from fastmcp.client.transports import SSETransport

        sse_kwargs: dict = {"url": config.url}
        if resolved_headers:
            sse_kwargs["headers"] = resolved_headers
        if config.timeout is not None:
            sse_kwargs["timeout"] = config.timeout

        toolset = FastMCPToolset(SSETransport(**sse_kwargs), max_retries=config.max_retries)
    elif config.transport == "streamable-http":
        from fastmcp.client.transports import StreamableHttpTransport

        http_kwargs: dict = {"url": config.url}
        if resolved_headers:
            http_kwargs["headers"] = resolved_headers
        if config.timeout is not None:
            http_kwargs["timeout"] = config.timeout

        toolset = FastMCPToolset(
            StreamableHttpTransport(**http_kwargs), max_retries=config.max_retries
        )
    else:
        raise ValueError(f"Unknown MCP transport: {config.transport}")

    # Apply tool_filter (allowlist) or tool_exclude (blocklist)
    if config.tool_filter:
        allowed = set(config.tool_filter)
        toolset = toolset.filtered(lambda _ctx, tool_def: tool_def.name in allowed)
    elif config.tool_exclude:
        excluded = set(config.tool_exclude)
        toolset = toolset.filtered(lambda _ctx, tool_def: tool_def.name not in excluded)

    # Apply tool_prefix
    if config.tool_prefix:
        toolset = toolset.prefixed(config.tool_prefix)

    return toolset
