"""Shared memory/session operations used by both CLI and TUI."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pydantic_ai.messages import ModelMessage

    from initrunner.agent.schema.role import RoleDefinition
    from initrunner.stores.base import MemoryStoreBase, MemoryType, SessionSummary

_logger = logging.getLogger(__name__)


@dataclass
class TurnResult:
    """Result of a turn finalization: trimmed messages and save status."""

    messages: list[ModelMessage]
    save_ok: bool


def clear_memories(
    role: RoleDefinition,
    *,
    sessions_only: bool = False,
    memories_only: bool = False,
    memory_type: MemoryType | None = None,
) -> bool:
    """Clear memory store. Returns True if a store was found and cleared."""
    from initrunner.stores.factory import open_memory_store

    with open_memory_store(role.spec.memory, role.metadata.name) as store:
        if store is None:
            return False
        if not memories_only:
            store.prune_sessions(role.metadata.name, keep_count=0)
        if not sessions_only:
            store.prune_memories(keep_count=0, memory_type=memory_type)
        return True


def export_memories(role: RoleDefinition) -> list[dict]:
    """Export all memories as a list of dicts."""
    from initrunner.stores.factory import open_memory_store

    with open_memory_store(role.spec.memory, role.metadata.name) as store:
        if store is None:
            return []
        memories = store.list_memories(limit=999999)
    return [
        {
            "id": m.id,
            "content": m.content,
            "category": m.category,
            "created_at": m.created_at,
            "memory_type": str(m.memory_type),
            "metadata": m.metadata,
        }
        for m in memories
    ]


def load_session(
    role: RoleDefinition,
    *,
    max_messages: int | None = None,
) -> list[ModelMessage] | None:
    """Load the latest session from the memory store."""
    from initrunner.stores.factory import open_memory_store

    if role.spec.memory is None:
        return None
    max_msgs = max_messages or role.spec.memory.max_resume_messages
    with open_memory_store(role.spec.memory, role.metadata.name) as store:
        if store is None:
            return None
        return store.load_latest_session(role.metadata.name, max_messages=max_msgs)


def save_session(
    role: RoleDefinition,
    session_id: str,
    messages: list[ModelMessage],
) -> bool:
    """Save a chat session to the memory store. Returns True on success."""
    from initrunner.stores.factory import open_memory_store

    with open_memory_store(role.spec.memory, role.metadata.name, require_exists=False) as store:
        if store is None:
            return True
        try:
            store.save_session(session_id, role.metadata.name, messages)
            return True
        except Exception:
            _logger.warning(
                "Failed to save session — conversation will not be resumable",
                exc_info=True,
            )
            return False


def list_sessions(role: RoleDefinition, limit: int = 20) -> list[SessionSummary]:
    """List stored sessions for a role."""
    from initrunner.stores.factory import open_memory_store

    if role.spec.memory is None:
        return []
    with open_memory_store(role.spec.memory, role.metadata.name) as store:
        if store is None:
            return []
        return store.list_sessions(role.metadata.name, limit=limit)


def load_session_by_id(
    role: RoleDefinition,
    session_id: str,
    max_messages: int | None = None,
) -> list[ModelMessage] | None:
    """Load a specific session by ID from the memory store."""
    from initrunner.stores.factory import open_memory_store

    if role.spec.memory is None:
        return None
    max_msgs = max_messages or role.spec.memory.max_resume_messages
    with open_memory_store(role.spec.memory, role.metadata.name) as store:
        if store is None:
            return None
        return store.load_session_by_id(session_id, role.metadata.name, max_messages=max_msgs)


def delete_session(role: RoleDefinition, session_id: str) -> bool:
    """Delete a specific session. Returns True if rows were deleted."""
    from initrunner.stores.factory import open_memory_store

    if role.spec.memory is None:
        return False
    with open_memory_store(role.spec.memory, role.metadata.name) as store:
        if store is None:
            return False
        return store.delete_session(session_id, role.metadata.name)


def build_memory_system_prompt(role: RoleDefinition) -> str:
    """Build a system prompt section from procedural memories. Never raises."""
    try:
        from initrunner.stores.base import MemoryType
        from initrunner.stores.factory import open_memory_store

        if role.spec.memory is None:
            return ""
        if not role.spec.memory.procedural.enabled:
            return ""

        with open_memory_store(role.spec.memory, role.metadata.name) as store:
            if store is None:
                return ""
            procedures = store.list_memories(limit=20, memory_type=MemoryType.PROCEDURAL)

        if not procedures:
            return ""

        lines = ["## Learned Procedures and Policies", ""]
        for mem in procedures:
            lines.append(f"- [{mem.category}] {mem.content}")

        return "\n".join(lines)
    except Exception:
        _logger.warning("Failed to load procedural memories for system prompt", exc_info=True)
        return ""


def finalize_turn(
    role: RoleDefinition,
    session_id: str,
    messages: list[ModelMessage],
    memory_store: MemoryStoreBase | None = None,
) -> TurnResult:
    """Trim history and persist the session.

    Returns TurnResult with trimmed history and save status.
    """
    from initrunner.agent.history import session_limits, trim_message_history

    _, max_history = session_limits(role)
    trimmed = trim_message_history(messages, max_history)

    save_ok = True
    if memory_store is not None:
        try:
            memory_store.save_session(session_id, role.metadata.name, trimmed)
        except Exception:
            _logger.warning(
                "Failed to save session — conversation will not be resumable",
                exc_info=True,
            )
            save_ok = False

    return TurnResult(messages=trimmed, save_ok=save_ok)
