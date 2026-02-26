"""Agent building and execution helpers."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

    from pydantic_ai import Agent
    from pydantic_ai.messages import ModelMessage

    from initrunner.agent.executor import AutonomousResult, RunResult
    from initrunner.agent.prompt import UserPrompt
    from initrunner.agent.schema.role import RoleDefinition
    from initrunner.audit.logger import AuditLogger
    from initrunner.stores.base import MemoryStoreBase


def build_agent_sync(path: Path) -> tuple[RoleDefinition, Agent]:
    """Load and build an agent from a role file (sync)."""
    from initrunner.agent.loader import load_and_build

    return load_and_build(path)


def build_agent_from_role_sync(role: RoleDefinition) -> Agent:
    """Build an agent from an in-memory RoleDefinition (no file path)."""
    from initrunner.agent.loader import build_agent

    return build_agent(role)


def execute_run_sync(
    agent: Agent,
    role: RoleDefinition,
    prompt: str | UserPrompt,
    *,
    audit_logger: AuditLogger | None = None,
    message_history: list[ModelMessage] | None = None,
) -> tuple[RunResult, list[ModelMessage]]:
    """Execute a single agent run (sync)."""
    from initrunner.agent.executor import execute_run

    return execute_run(
        agent,
        role,
        prompt,
        audit_logger=audit_logger,
        message_history=message_history,
    )


def execute_autonomous_sync(
    agent: Agent,
    role: RoleDefinition,
    prompt: str | UserPrompt,
    *,
    audit_logger: AuditLogger | None = None,
    memory_store: MemoryStoreBase | None = None,
    max_iterations_override: int | None = None,
) -> AutonomousResult:
    """Execute an autonomous agentic loop (sync)."""
    from initrunner.runner import run_autonomous

    return run_autonomous(
        agent,
        role,
        prompt,
        audit_logger=audit_logger,
        memory_store=memory_store,
        max_iterations_override=max_iterations_override,
    )


def execute_run_stream_sync(
    agent: Agent,
    role: RoleDefinition,
    prompt: str | UserPrompt,
    *,
    audit_logger: AuditLogger | None = None,
    message_history: list[ModelMessage] | None = None,
    on_token: Callable[[str], None] | None = None,
) -> tuple[RunResult, list[ModelMessage]]:
    """Execute a streaming agent run (sync). Call from a worker thread."""
    from initrunner.agent.executor import execute_run_stream

    return execute_run_stream(
        agent,
        role,
        prompt,
        audit_logger=audit_logger,
        message_history=message_history,
        on_token=on_token,
    )
