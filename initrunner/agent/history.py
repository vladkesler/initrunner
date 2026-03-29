"""Message-history utilities shared by the CLI runner and TUI."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic_ai.messages import ModelMessage, ModelResponse

from initrunner.agent.history_compaction import maybe_compact_message_history

if TYPE_CHECKING:
    from initrunner.agent.schema.autonomy import AutonomyConfig
    from initrunner.agent.schema.role import RoleDefinition

__all__ = [
    "maybe_compact_message_history",
    "reduce_history",
    "session_limits",
    "trim_message_history",
]


def trim_message_history(
    messages: list[ModelMessage],
    max_messages: int,
    *,
    preserve_first: bool = False,
) -> list[ModelMessage]:
    """Trim message history to at most *max_messages*, keeping the most recent.

    Ensures the trimmed list starts with a request, not a response.
    If *preserve_first* is True, the first message (original task) is always
    kept and the budget is filled from the tail.
    """
    if len(messages) <= max_messages:
        return messages

    if preserve_first and max_messages >= 2 and messages:
        first = messages[0]
        tail = messages[-(max_messages - 1) :]
        while tail and isinstance(tail[0], ModelResponse):
            tail = tail[1:]
        return [first, *tail]

    trimmed = messages[-max_messages:]
    while trimmed and isinstance(trimmed[0], ModelResponse):
        trimmed = trimmed[1:]
    return trimmed


def reduce_history(
    messages: list[ModelMessage],
    autonomy_config: AutonomyConfig,
    role: RoleDefinition,
    *,
    preserve_first: bool = False,
) -> list[ModelMessage]:
    """Compact, trim, then enforce token budget in one step.

    Combines :func:`maybe_compact_message_history`,
    :func:`trim_message_history`, and :func:`enforce_token_budget` -- the
    sequence that autonomous and daemon runners both need after each
    iteration.
    """
    compacted = maybe_compact_message_history(
        messages, autonomy_config, role, preserve_first=preserve_first
    )
    trimmed = trim_message_history(
        compacted,
        autonomy_config.max_history_messages,
        preserve_first=preserve_first,
    )

    from initrunner.agent.history_summarizer import (
        _BUDGET_FRACTION,
        enforce_token_budget,
        resolve_context_window,
    )

    ctx_window = resolve_context_window(role.spec.model)  # type: ignore[union-attr]
    token_budget = int(ctx_window * _BUDGET_FRACTION)
    return enforce_token_budget(trimmed, token_budget, preserve_first=preserve_first)


def session_limits(role: RoleDefinition) -> tuple[int, int]:
    """Return ``(max_resume, max_history)`` derived from the role's memory config."""
    max_resume = 20
    if role.spec.memory is not None:
        max_resume = role.spec.memory.max_resume_messages
    return max_resume, max_resume * 2
