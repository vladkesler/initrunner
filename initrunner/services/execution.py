"""Agent building and execution helpers."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

    from pydantic_ai import Agent
    from pydantic_ai.messages import ModelMessage
    from pydantic_ai.models import Model

    from initrunner.agent.executor import AutonomousResult, RunResult
    from initrunner.agent.prompt import UserPrompt
    from initrunner.agent.schema.role import RoleDefinition
    from initrunner.audit.logger import AuditLogger
    from initrunner.stores.base import MemoryStoreBase


def build_agent_sync(
    path: Path,
    extra_skill_dirs: list[Path] | None = None,
    model_override: str | None = None,
) -> tuple[RoleDefinition, Agent]:
    """Load and build an agent from a role file (sync)."""
    from initrunner.agent.loader import load_and_build

    return load_and_build(path, extra_skill_dirs=extra_skill_dirs, model_override=model_override)


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
    model_override: Model | str | None = None,
    trigger_type: str | None = None,
    trigger_metadata: dict[str, str] | None = None,
    skip_input_validation: bool = False,
    principal_id: str | None = None,
) -> tuple[RunResult, list[ModelMessage]]:
    """Execute a single agent run (sync)."""
    from initrunner.agent.executor import execute_run

    return execute_run(
        agent,
        role,
        prompt,
        audit_logger=audit_logger,
        message_history=message_history,
        model_override=model_override,
        trigger_type=trigger_type,
        trigger_metadata=trigger_metadata,
        skip_input_validation=skip_input_validation,
        principal_id=principal_id,
    )


def execute_autonomous_sync(
    agent: Agent,
    role: RoleDefinition,
    prompt: str | UserPrompt,
    *,
    audit_logger: AuditLogger | None = None,
    memory_store: MemoryStoreBase | None = None,
    max_iterations_override: int | None = None,
    principal_id: str | None = None,
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
    model_override: Model | str | None = None,
    on_token: Callable[[str], None] | None = None,
    skip_input_validation: bool = False,
    principal_id: str | None = None,
) -> tuple[RunResult, list[ModelMessage]]:
    """Execute a streaming agent run (sync). Call from a worker thread."""
    from initrunner.agent.executor import execute_run_stream

    return execute_run_stream(
        agent,
        role,
        prompt,
        audit_logger=audit_logger,
        message_history=message_history,
        model_override=model_override,
        on_token=on_token,
        skip_input_validation=skip_input_validation,
        principal_id=principal_id,
    )


async def execute_run_async(
    agent: Agent,
    role: RoleDefinition,
    prompt: str | UserPrompt,
    *,
    audit_logger: AuditLogger | None = None,
    message_history: list[ModelMessage] | None = None,
    model_override: Model | str | None = None,
    skip_input_validation: bool = False,
    principal_id: str | None = None,
) -> tuple[RunResult, list[ModelMessage]]:
    """Execute a single agent run (async)."""
    from initrunner.agent.executor import execute_run_async as _execute_run_async

    return await _execute_run_async(
        agent,
        role,
        prompt,
        audit_logger=audit_logger,
        message_history=message_history,
        model_override=model_override,
        skip_input_validation=skip_input_validation,
        principal_id=principal_id,
    )


async def execute_run_stream_async(
    agent: Agent,
    role: RoleDefinition,
    prompt: str | UserPrompt,
    *,
    audit_logger: AuditLogger | None = None,
    message_history: list[ModelMessage] | None = None,
    model_override: Model | str | None = None,
    on_token: Callable[[str], None] | None = None,
    skip_input_validation: bool = False,
    principal_id: str | None = None,
) -> tuple[RunResult, list[ModelMessage]]:
    """Execute a streaming agent run (async)."""
    from initrunner.agent.executor import execute_run_stream_async as _stream_async

    return await _stream_async(
        agent,
        role,
        prompt,
        audit_logger=audit_logger,
        message_history=message_history,
        model_override=model_override,
        on_token=on_token,
        skip_input_validation=skip_input_validation,
        principal_id=principal_id,
    )
