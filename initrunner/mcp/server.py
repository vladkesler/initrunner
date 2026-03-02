"""FastMCPToolset wrapper for McpToolConfig."""

from __future__ import annotations

from pydantic_ai.toolsets.abstract import AbstractToolset
from pydantic_ai.toolsets.fastmcp import FastMCPToolset

from initrunner.agent.schema.tools import McpToolConfig
from initrunner.agent.tools._registry import ToolBuildContext, register_tool
from initrunner.mcp._transport import build_transport


@register_tool("mcp", McpToolConfig)
def build_mcp_toolset(
    config: McpToolConfig,
    ctx: ToolBuildContext,
) -> AbstractToolset:
    """Build a FastMCPToolset from an McpToolConfig."""
    sandbox = ctx.role.spec.security.tools

    transport = build_transport(config, ctx.role_dir, sandbox=sandbox)
    toolset = FastMCPToolset(transport, max_retries=config.max_retries)

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
