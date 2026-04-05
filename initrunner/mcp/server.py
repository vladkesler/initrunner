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
    if config.defer:
        return _build_deferred(config, ctx)
    return _build_eager(config, ctx)


def _build_eager(config: McpToolConfig, ctx: ToolBuildContext) -> AbstractToolset:
    """Connect immediately (default behaviour)."""
    sandbox = ctx.role.spec.security.tools
    transport = build_transport(config, ctx.role_dir, sandbox=sandbox)
    toolset: AbstractToolset = FastMCPToolset(transport, max_retries=config.max_retries)
    return _apply_filters(toolset, config)


def _build_deferred(config: McpToolConfig, ctx: ToolBuildContext) -> AbstractToolset:
    """Defer connection until first tool call, serving cached schemas in the meantime."""
    from initrunner.mcp._cache import cache_key, read_cache, to_tool_definitions
    from initrunner.mcp._deferred import DeferredMcpToolset

    key = cache_key(config, ctx.role_dir)
    entry = read_cache(key)
    cached_defs = to_tool_definitions(entry) if entry else None

    sandbox = ctx.role.spec.security.tools
    role_dir = ctx.role_dir

    def factory() -> FastMCPToolset:
        transport = build_transport(config, role_dir, sandbox=sandbox)
        return FastMCPToolset(transport, max_retries=config.max_retries)

    toolset: AbstractToolset = DeferredMcpToolset(
        cached_defs=cached_defs,
        factory=factory,
        cache_key=key,
        max_retries=config.max_retries,
    )
    return _apply_filters(toolset, config)


def _apply_filters(toolset: AbstractToolset, config: McpToolConfig) -> AbstractToolset:
    """Apply tool_filter, tool_exclude, and tool_prefix wrappers."""
    if config.tool_filter:
        allowed = set(config.tool_filter)
        toolset = toolset.filtered(lambda _ctx, tool_def: tool_def.name in allowed)
    elif config.tool_exclude:
        excluded = set(config.tool_exclude)
        toolset = toolset.filtered(lambda _ctx, tool_def: tool_def.name not in excluded)
    if config.tool_prefix:
        toolset = toolset.prefixed(config.tool_prefix)
    return toolset
