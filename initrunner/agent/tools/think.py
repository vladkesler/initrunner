"""Think tool: lets the agent reason without user-visible output."""

from __future__ import annotations

from pydantic_ai.toolsets.function import FunctionToolset

from initrunner.agent.schema.tools import ThinkToolConfig
from initrunner.agent.tools._registry import ToolBuildContext, register_tool


@register_tool("think", ThinkToolConfig)
def build_think_toolset(config: ThinkToolConfig, ctx: ToolBuildContext) -> FunctionToolset:
    """Build a FunctionToolset with a single ``think`` tool."""
    toolset = FunctionToolset()

    @toolset.tool
    def think(thought: str) -> str:
        """Use this tool to think step-by-step before acting.
        Your thoughts are not shown to the user. Use for:
        - Breaking down complex tasks
        - Reasoning about which tool to use next
        - Planning multi-step approaches
        - Reflecting on results before responding
        """
        return "Thought recorded."

    return toolset
