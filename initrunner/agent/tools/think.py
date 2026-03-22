"""Think tool: structured chain-of-thought with optional self-critique."""

from __future__ import annotations

from pydantic_ai.toolsets.function import FunctionToolset

from initrunner.agent.reasoning import ThinkState
from initrunner.agent.schema.tools import ThinkToolConfig
from initrunner.agent.tools._registry import ToolBuildContext, register_tool

_CRITIQUE_EVERY = 5


@register_tool("think", ThinkToolConfig, run_scoped=True)
def build_think_toolset(
    config: ThinkToolConfig,
    ctx: ToolBuildContext,
) -> FunctionToolset:
    """Build a think toolset with accumulated reasoning chain."""
    state = ThinkState(max_thoughts=config.max_thoughts)
    critique = config.critique
    toolset = FunctionToolset()

    @toolset.tool_plain
    def think(thought: str) -> str:
        """Use this tool to think step-by-step before acting.
        Your thoughts are not shown to the user. Use for:
        - Breaking down complex tasks
        - Reasoning about which tool to use next
        - Planning multi-step approaches
        - Reflecting on results before responding
        """
        result = state.record(thought)
        if critique and len(state.thoughts) % _CRITIQUE_EVERY == 0:
            result += (
                f"\n\nYou have recorded {len(state.thoughts)} thoughts. "
                "Before proceeding, critically evaluate your reasoning so far. "
                "What assumptions might be wrong? What have you missed?"
            )
        return result

    return toolset
