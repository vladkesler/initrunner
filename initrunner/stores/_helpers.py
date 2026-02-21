"""Backend-agnostic helpers shared across store implementations."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic_ai.messages import (
    ModelMessage,
    ModelMessagesTypeAdapter,
    ModelRequest,
    ModelResponse,
    SystemPromptPart,
)

if TYPE_CHECKING:
    pass


def _filter_system_prompts(messages: list[ModelMessage]) -> list[ModelMessage]:
    """Return messages with SystemPromptPart entries removed from ModelRequest parts."""
    filtered: list[ModelMessage] = []
    for msg in messages:
        if isinstance(msg, ModelRequest):
            new_parts = [p for p in msg.parts if not isinstance(p, SystemPromptPart)]
            if new_parts:
                filtered.append(ModelRequest(parts=new_parts))
        else:
            filtered.append(msg)
    return filtered


def _process_loaded_messages(
    json_data: bytes | str, max_messages: int
) -> list[ModelMessage] | None:
    """Parse, trim, and validate a stored message list."""
    messages: list[ModelMessage] = list(ModelMessagesTypeAdapter.validate_json(json_data))
    if not messages:
        return None
    if len(messages) > max_messages:
        messages = messages[-max_messages:]
    while messages and isinstance(messages[0], ModelResponse):
        messages.pop(0)
    return messages if messages else None


def _glob_to_sql_like(pattern: str) -> str:
    """Convert a simple glob pattern to a SQL LIKE pattern.

    Handles ``*`` → ``%`` and ``?`` → ``_``, escaping literal ``%`` and ``_``.
    Does NOT handle bracket expressions (``[...]``).
    """
    like: list[str] = []
    for ch in pattern:
        if ch == "*":
            like.append("%")
        elif ch == "?":
            like.append("_")
        elif ch in ("%", "_", "\\"):
            like.append("\\")
            like.append(ch)
        else:
            like.append(ch)
    return "".join(like)
