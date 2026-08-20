"""Registry shim for the ``mcp`` tool type.

The MCP client stack (``pydantic_ai.mcp`` and fastmcp underneath it) is an
optional extra.  Registration has to happen in a core install anyway, or
``type: mcp`` would stop validating and every schema, doctor and wizard
surface would lose the tool type.  So the config class registers here and the
heavy import stays inside the builder: nothing MCP-related is imported until a
role that actually configures an MCP server is built.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from initrunner.agent.schema.tools import McpToolConfig
from initrunner.agent.tools._registry import ToolBuildContext, register_tool

if TYPE_CHECKING:
    from pydantic_ai.toolsets.abstract import AbstractToolset


@register_tool("mcp", McpToolConfig)
def build_mcp_toolset(config: McpToolConfig, ctx: ToolBuildContext) -> AbstractToolset:
    """Build an MCPToolset, or raise ``MissingExtraError`` without the extra."""
    from initrunner._compat import require_mcp

    require_mcp()

    from initrunner.mcp.server import build_mcp_toolset as _build_mcp_toolset

    return _build_mcp_toolset(config, ctx)
