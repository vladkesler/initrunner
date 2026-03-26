"""Clarify tool: agent-initiated mid-run user clarification."""

from __future__ import annotations

from pydantic_ai.toolsets.function import FunctionToolset

from initrunner.agent.clarify import ClarifyState, get_clarify_callback
from initrunner.agent.schema.tools import ClarifyToolConfig
from initrunner.agent.tools._registry import ToolBuildContext, register_tool


@register_tool("clarify", ClarifyToolConfig, run_scoped=True)
def build_clarify_toolset(
    config: ClarifyToolConfig,
    ctx: ToolBuildContext,
) -> FunctionToolset:
    """Build a clarify toolset that pauses execution for user input."""
    state = ClarifyState(max_clarifications=config.max_clarifications)
    toolset = FunctionToolset()

    @toolset.tool_plain
    def clarify(question: str) -> str:
        """Ask the user a clarifying question and wait for their response.

        Use this when you need information that cannot be inferred from context.
        Do NOT use for confirmation of actions -- proceed with your best judgment.
        Do NOT use repeatedly -- batch your questions when possible.

        Args:
            question: The specific question to ask the user.
        """
        if state.count >= state.max_clarifications:
            return (
                f"Clarification limit reached ({state.max_clarifications}). "
                "Proceed with your best judgment based on available information."
            )

        callback = get_clarify_callback()
        if callback is None:
            return (
                "Clarification is not available in this execution mode. "
                "Proceed with your best judgment."
            )

        state.count += 1
        try:
            answer = callback(question)
        except TimeoutError:
            return "No response received within the timeout. Proceed with your best judgment."
        except Exception as e:
            return f"Failed to get clarification: {e}. Proceed with your best judgment."

        state.history.append((question, answer))
        return f"User response: {answer}"

    return toolset
