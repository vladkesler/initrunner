"""Message-history utilities shared by the CLI runner and TUI."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic_ai.messages import ModelMessage, ModelResponse

if TYPE_CHECKING:
    from initrunner.agent.schema import RoleDefinition


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


def session_limits(role: RoleDefinition) -> tuple[int, int]:
    """Return ``(max_resume, max_history)`` derived from the role's memory config."""
    max_resume = 20
    if role.spec.memory is not None:
        max_resume = role.spec.memory.max_resume_messages
    return max_resume, max_resume * 2
