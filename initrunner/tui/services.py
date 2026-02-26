"""Async bridge to sync initrunner core for TUI screens."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from initrunner.services.discovery import (
    DiscoveredRole,  # re-export for TUI screens
    discover_roles_sync,
    validate_role_sync,
)
from initrunner.services.execution import (
    build_agent_from_role_sync,
    build_agent_sync,
    execute_run_stream_sync,
    execute_run_sync,
)
from initrunner.services.memory import (
    clear_memories_sync,
    delete_session_sync,
    export_memories_sync,
    list_memories_sync,
    list_sessions_sync,
    load_session_by_id_sync,
    load_session_sync,
    save_session_sync,
)
from initrunner.services.operations import (
    query_audit_sync,
    run_ingest_sync,
    start_triggers_sync,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from pydantic_ai import Agent

    from initrunner.agent.executor import RunResult
    from initrunner.agent.prompt import UserPrompt
    from initrunner.agent.schema.role import RoleDefinition
    from initrunner.audit.logger import AuditRecord
    from initrunner.stores.base import Memory, SessionSummary

__all__ = ["DiscoveredRole", "ServiceBridge"]


class ServiceBridge:
    """Async bridge wrapping shared services functions via asyncio.to_thread().

    Each method wraps a sync operation in asyncio.to_thread() so it can
    be awaited from Textual's async event loop without blocking the UI.
    """

    @staticmethod
    async def discover_roles(dirs: list[Path]) -> list[DiscoveredRole]:
        return await asyncio.to_thread(discover_roles_sync, dirs)

    @staticmethod
    async def validate_role(path: Path) -> DiscoveredRole:
        return await asyncio.to_thread(validate_role_sync, path)

    @staticmethod
    async def build_agent(path: Path) -> tuple[RoleDefinition, Agent]:
        return await asyncio.to_thread(build_agent_sync, path)

    @staticmethod
    async def build_quick_chat_role() -> tuple[RoleDefinition, str, str]:
        from initrunner.services.providers import build_quick_chat_role_sync

        return await asyncio.to_thread(build_quick_chat_role_sync)

    @staticmethod
    async def build_agent_from_role(role: RoleDefinition) -> Agent:
        return await asyncio.to_thread(build_agent_from_role_sync, role)

    @staticmethod
    async def sense_role(prompt: str, role_dir: Path | None = None) -> Any:
        from initrunner.services.role_selector import select_role_sync

        return await asyncio.to_thread(select_role_sync, prompt, role_dir=role_dir)

    @staticmethod
    async def run_agent(
        agent: Agent,
        role: RoleDefinition,
        prompt: str | UserPrompt,
        *,
        audit_logger: Any = None,
        message_history: list | None = None,
    ) -> tuple[RunResult, list]:
        return await asyncio.to_thread(
            execute_run_sync,
            agent,
            role,
            prompt,
            audit_logger=audit_logger,
            message_history=message_history,
        )

    @staticmethod
    def run_agent_streamed(
        agent: Agent,
        role: RoleDefinition,
        prompt: str | UserPrompt,
        *,
        audit_logger: Any = None,
        message_history: list | None = None,
        on_token: Callable[[str], None] | None = None,
    ) -> tuple[RunResult, list]:
        """Sync streaming wrapper — call from a worker thread.

        Uses execute_run_stream_sync() to stream tokens with full guardrails,
        audit logging, and content policy enforcement.
        """
        return execute_run_stream_sync(
            agent,
            role,
            prompt,
            audit_logger=audit_logger,
            message_history=message_history,
            on_token=on_token,
        )

    @staticmethod
    async def query_audit(
        *,
        agent_name: str | None = None,
        since: str | None = None,
        until: str | None = None,
        limit: int = 100,
    ) -> list[AuditRecord]:
        return await asyncio.to_thread(
            query_audit_sync,
            agent_name=agent_name,
            since=since,
            until=until,
            limit=limit,
        )

    @staticmethod
    async def run_ingest(
        role: RoleDefinition,
        role_path: Path,
        *,
        force: bool = False,
        progress_callback: Callable[[Path, Any], None] | None = None,
    ) -> Any:
        return await asyncio.to_thread(
            run_ingest_sync,
            role,
            role_path,
            force=force,
            progress_callback=progress_callback,
        )

    @staticmethod
    async def list_memories(
        role: RoleDefinition,
        *,
        category: str | None = None,
        limit: int = 100,
    ) -> list[Memory]:
        return await asyncio.to_thread(
            list_memories_sync,
            role,
            category=category,
            limit=limit,
        )

    @staticmethod
    async def clear_memories(
        role: RoleDefinition,
        *,
        sessions_only: bool = False,
        memories_only: bool = False,
    ) -> None:
        return await asyncio.to_thread(
            clear_memories_sync,
            role,
            sessions_only=sessions_only,
            memories_only=memories_only,
        )

    @staticmethod
    async def export_memories(role: RoleDefinition) -> list[dict]:
        return await asyncio.to_thread(export_memories_sync, role)

    @staticmethod
    async def save_session(
        role: RoleDefinition,
        session_id: str,
        messages: list,
    ) -> bool:
        return await asyncio.to_thread(
            save_session_sync,
            role,
            session_id,
            messages,
        )

    @staticmethod
    async def load_session(
        role: RoleDefinition,
        *,
        max_messages: int | None = None,
    ) -> list | None:
        return await asyncio.to_thread(
            load_session_sync,
            role,
            max_messages=max_messages,
        )

    @staticmethod
    async def list_sessions(
        role: RoleDefinition,
        limit: int = 20,
    ) -> list[SessionSummary]:
        return await asyncio.to_thread(
            list_sessions_sync,
            role,
            limit=limit,
        )

    @staticmethod
    async def load_session_by_id(
        role: RoleDefinition,
        session_id: str,
        max_messages: int | None = None,
    ) -> list | None:
        return await asyncio.to_thread(
            load_session_by_id_sync,
            role,
            session_id,
            max_messages=max_messages,
        )

    @staticmethod
    async def delete_session(
        role: RoleDefinition,
        session_id: str,
    ) -> bool:
        return await asyncio.to_thread(
            delete_session_sync,
            role,
            session_id,
        )

    @staticmethod
    async def start_triggers(
        role: RoleDefinition,
        callback: Callable[[Any], None],
    ) -> Any:
        """Build and start triggers. Returns TriggerDispatcher."""
        return await asyncio.to_thread(
            start_triggers_sync,
            role,
            callback,
        )
