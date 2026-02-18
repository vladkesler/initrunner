"""Session and memory CRUD operations."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pydantic_ai.messages import ModelMessage

    from initrunner.agent.schema.role import RoleDefinition
    from initrunner.stores.base import Memory, MemoryType, SessionSummary


def list_memories_sync(
    role: RoleDefinition,
    *,
    category: str | None = None,
    limit: int = 100,
    memory_type: MemoryType | None = None,
) -> list[Memory]:
    """List memories for a role (sync)."""
    from initrunner.stores.factory import open_memory_store

    with open_memory_store(role.spec.memory, role.metadata.name) as store:
        if store is None:
            return []
        return store.list_memories(category=category, limit=limit, memory_type=memory_type)


def clear_memories_sync(
    role: RoleDefinition, *, sessions_only: bool = False, memories_only: bool = False
) -> None:
    """Clear memory store (sync). Delegates to shared domain function."""
    from initrunner.agent.memory_ops import clear_memories

    clear_memories(role, sessions_only=sessions_only, memories_only=memories_only)


def export_memories_sync(role: RoleDefinition) -> list[dict]:
    """Export memories as dicts (sync). Delegates to shared domain function."""
    from initrunner.agent.memory_ops import export_memories

    return export_memories(role)


def save_session_sync(
    role: RoleDefinition,
    session_id: str,
    messages: list[ModelMessage],
) -> bool:
    """Save a chat session to the memory store (sync). Returns True on success."""
    from initrunner.agent.memory_ops import save_session

    return save_session(role, session_id, messages)


def load_session_sync(
    role: RoleDefinition,
    *,
    max_messages: int | None = None,
) -> list[ModelMessage] | None:
    """Load the latest session from the memory store (sync)."""
    from initrunner.agent.memory_ops import load_session

    return load_session(role, max_messages=max_messages)


def list_sessions_sync(role: RoleDefinition, limit: int = 20) -> list[SessionSummary]:
    """List stored sessions for a role (sync)."""
    from initrunner.agent.memory_ops import list_sessions

    return list_sessions(role, limit=limit)


def load_session_by_id_sync(
    role: RoleDefinition,
    session_id: str,
    max_messages: int | None = None,
) -> list[ModelMessage] | None:
    """Load a specific session by ID (sync)."""
    from initrunner.agent.memory_ops import load_session_by_id

    return load_session_by_id(role, session_id, max_messages=max_messages)


def delete_session_sync(role: RoleDefinition, session_id: str) -> bool:
    """Delete a specific session (sync). Returns True if rows were deleted."""
    from initrunner.agent.memory_ops import delete_session

    return delete_session(role, session_id)


def export_session_markdown_sync(role: RoleDefinition, messages: list[ModelMessage]) -> str:
    """Convert a ModelMessage list to a markdown string for export."""
    from pydantic_ai.messages import (
        ModelRequest,
        ModelResponse,
        TextPart,
        UserPromptPart,
    )

    from initrunner.agent.prompt import render_content_as_text

    lines: list[str] = []
    lines.append(f"# Chat Export — {role.metadata.name}")
    lines.append("")

    for msg in messages:
        if isinstance(msg, ModelRequest):
            for part in msg.parts:
                if isinstance(part, UserPromptPart):
                    if isinstance(part.content, str):
                        lines.append(f"**You:** {part.content}")
                    elif isinstance(part.content, list):
                        text_parts = [render_content_as_text(item) for item in part.content]
                        lines.append(f"**You:** {' '.join(text_parts)}")
                    else:
                        lines.append(f"**You:** {part.content}")
                    lines.append("")
        elif isinstance(msg, ModelResponse):
            for part in msg.parts:
                if isinstance(part, TextPart):
                    lines.append(f"**Agent:** {part.content}")
                    lines.append("")

    return "\n".join(lines)
