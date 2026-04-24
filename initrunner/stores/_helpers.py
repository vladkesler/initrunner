"""Backend-agnostic helpers shared across store implementations."""

from __future__ import annotations

import dataclasses
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
    """Return messages normalized for persistence.

    - ``SystemPromptPart`` entries are removed from each ``ModelRequest.parts``
      (our static directive now flows through ``Agent.instructions`` instead).
    - ``ModelRequest`` metadata (timestamp, run_id, metadata, etc.) is preserved
      via ``dataclasses.replace`` rather than dropped by bare reconstruction.
    - ``ModelRequest.instructions`` is retained only on the newest two retained
      requests -- matching PydanticAI's ``_get_instructions`` resolver, which
      falls back from the newest request to the second-most-recent when the
      newest is a mock tool-return. Older requests' ``instructions`` are
      nulled to keep saved sessions tight.
    - Requests that become empty after stripping are dropped entirely.
    """
    filtered: list[ModelMessage] = []
    for msg in messages:
        if isinstance(msg, ModelRequest):
            new_parts = [p for p in msg.parts if not isinstance(p, SystemPromptPart)]
            if not new_parts:
                continue
            filtered.append(dataclasses.replace(msg, parts=new_parts))
        else:
            filtered.append(msg)

    kept = 0
    for i in range(len(filtered) - 1, -1, -1):
        msg = filtered[i]
        if not isinstance(msg, ModelRequest):
            continue
        if kept < 2:
            kept += 1
            continue
        if msg.instructions is not None:
            filtered[i] = dataclasses.replace(msg, instructions=None)

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
