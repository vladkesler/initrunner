"""Blackboard tool: shared structured state for in-run agent coordination.

A flow agent posts, reads, and claims entries on a per-run blackboard that
lives in the flow graph state. Posting under a key lets a downstream agent (or
a fan-in join) read a structured value without it being threaded through prompt
text. The tool is run-scoped: it is built fresh for each agent step with the
flow's live :class:`~initrunner.flow.graph.Blackboard` injected, mirroring how
``todo`` receives a fresh ``ReflectionState``. Outside a flow there is no
blackboard, so the tool is never built.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from pydantic_ai.toolsets.function import FunctionToolset

from initrunner.agent.schema.tools import BlackboardToolConfig
from initrunner.agent.tools._registry import ToolBuildContext, register_tool

if TYPE_CHECKING:
    from initrunner.flow.graph import Blackboard

# Posted keys must be short, predictable identifiers so agents can agree on
# them by convention. Bound the readable summary line so a board listing can
# never blow past a reasonable tool-result size.
_MAX_KEY_CHARS = 64
_LIST_VALUE_PREVIEW_CHARS = 80


def _valid_key(key: str) -> bool:
    return bool(key) and len(key) <= _MAX_KEY_CHARS and key.replace("_", "").isalnum()


@register_tool("blackboard", BlackboardToolConfig, run_scoped=True)
def build_blackboard_toolset(
    config: BlackboardToolConfig,
    ctx: ToolBuildContext,
    blackboard: Blackboard,
) -> FunctionToolset:
    """Build the post/read/claim/list toolset bound to a flow blackboard."""
    blackboard.max_entries = config.max_entries
    author = ctx.role.metadata.name
    max_value_chars = config.max_value_chars
    toolset = FunctionToolset(sequential=True)

    @toolset.tool_plain
    def blackboard_post(key: str, value: str) -> str:
        """Post a value to the shared blackboard under a key.

        Downstream agents and fan-in joins can read it by the same key. The
        value is stored verbatim as a string; pass JSON if you need structure.

        Args:
            key: Unique identifier (letters, digits, underscore; max 64 chars).
            value: The string payload to share.
        """
        if not _valid_key(key):
            return (
                "Error: invalid key. Use letters, digits and underscore only, "
                f"max {_MAX_KEY_CHARS} chars."
            )
        if len(value) > max_value_chars:
            return f"Error: value too large ({len(value)} > {max_value_chars} chars)."
        try:
            entry_id = blackboard.post(key, value, author)
        except ValueError as exc:
            return f"Error: {exc}"
        return f"Posted '{key}' as {entry_id}."

    @toolset.tool_plain
    def blackboard_read(key: str) -> str:
        """Read a value from the shared blackboard without removing it.

        Args:
            key: The key to read.
        """
        try:
            entry = blackboard.read(key)
        except ValueError as exc:
            return f"Error: {exc}"
        return json.dumps(entry)

    @toolset.tool_plain
    def blackboard_claim(key: str) -> str:
        """Read and remove an entry so no other agent can claim it again.

        Use this for work-stealing handoffs where exactly one consumer should
        take a posted item.

        Args:
            key: The key to claim.
        """
        try:
            return blackboard.claim(key)
        except ValueError as exc:
            return f"Error: {exc}"

    @toolset.tool_plain
    def blackboard_list() -> str:
        """List the keys currently on the shared blackboard with a short preview."""
        return blackboard.summarize(_LIST_VALUE_PREVIEW_CHARS)

    return toolset
