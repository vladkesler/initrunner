"""Agent building and execution helpers."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

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
    on_partial: Callable[[Any], None] | None = None,
    skip_input_validation: bool = False,
    principal_id: str | None = None,
) -> tuple[RunResult, list[ModelMessage]]:
    """Execute a streaming agent run (sync). Call from a worker thread.

    ``on_token`` fires for text-output roles. ``on_partial`` fires for
    structured-output roles with each progressively-validated partial.
    """
    from initrunner.agent.executor import execute_run_stream

    return execute_run_stream(
        agent,
        role,
        prompt,
        audit_logger=audit_logger,
        message_history=message_history,
        model_override=model_override,
        on_token=on_token,
        on_partial=on_partial,
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


def persist_paused_run(
    audit_logger: AuditLogger,
    result: RunResult,
    role: RoleDefinition,
    message_history: list[ModelMessage],
    *,
    role_path: Path | None = None,
) -> None:
    """Persist pending-approval state so the run can be resumed later.

    Call immediately after ``execute_run`` / ``execute_run_async`` returns
    with ``status="paused"``. Serializes the message history once and
    writes one row per pending approval.
    """
    from pydantic_ai.messages import ModelMessagesTypeAdapter

    history_json = ModelMessagesTypeAdapter.dump_json(message_history).decode()
    role_path_str = str(role_path) if role_path else None
    for pending in result.pending_approvals:
        audit_logger.record_pending_approval(
            run_id=result.run_id,
            tool_call_id=pending.tool_call_id,
            tool_name=pending.tool_name,
            agent_name=role.metadata.name,
            role_path=role_path_str,
            arguments_json=_args_to_json(pending.arguments),
            message_history_json=history_json,
        )


def _args_to_json(args: dict) -> str:
    """Serialize tool-call arguments to JSON for persistence."""
    import json

    try:
        return json.dumps(args, default=str)
    except (TypeError, ValueError):
        return json.dumps({"_unserializable": True})


def load_pending_state(
    audit_logger: AuditLogger,
    run_id: str,
) -> tuple[list[ModelMessage], list] | None:
    """Hydrate the message history + pending rows for a paused run.

    Returns ``None`` if no unresolved pending rows exist for *run_id*.
    All rows for the same run share an identical message history, so we
    deserialize once from the first row.
    """
    from pydantic_ai.messages import ModelMessagesTypeAdapter

    rows = audit_logger.load_pending_approvals(run_id)
    unresolved = [r for r in rows if r.resolved_at is None]
    if not unresolved:
        return None
    history = ModelMessagesTypeAdapter.validate_json(unresolved[0].message_history_json)
    return history, unresolved


def resume_run_sync(
    agent: Agent,
    role: RoleDefinition,
    run_id: str,
    approvals: dict[str, bool],
    *,
    audit_logger: AuditLogger,
    resolved_by: str | None = None,
    role_path: Path | None = None,
    model_override: Model | str | None = None,
    principal_id: str | None = None,
) -> tuple[RunResult, list[ModelMessage]]:
    """Resume a paused run (sync).

    Loads stored state, invokes the agent with approvals, resolves the
    pending rows, and — if the model queues more approval-required calls
    — persists the fresh paused state so another resume can pick it up.
    """
    from initrunner.agent.executor import execute_run_resume

    state = load_pending_state(audit_logger, run_id)
    if state is None:
        raise ValueError(f"No unresolved approvals found for run {run_id!r}")
    message_history, pending_rows = state
    missing = [row.tool_call_id for row in pending_rows if row.tool_call_id not in approvals]
    if missing:
        raise ValueError(f"Missing decisions for tool_call_ids: {missing}")

    result, new_messages = execute_run_resume(
        agent,
        role,
        run_id=run_id,
        message_history=message_history,
        approvals=approvals,
        audit_logger=audit_logger,
        model_override=model_override,
        principal_id=principal_id,
    )
    for tool_call_id, decision in approvals.items():
        audit_logger.resolve_pending_approval(
            run_id=run_id,
            tool_call_id=tool_call_id,
            decision=decision,
            resolved_by=resolved_by,
        )
    if result.status == "paused":
        persist_paused_run(audit_logger, result, role, new_messages, role_path=role_path)
    return result, new_messages


async def resume_run_async(
    agent: Agent,
    role: RoleDefinition,
    run_id: str,
    approvals: dict[str, bool],
    *,
    audit_logger: AuditLogger,
    resolved_by: str | None = None,
    role_path: Path | None = None,
    model_override: Model | str | None = None,
    principal_id: str | None = None,
) -> tuple[RunResult, list[ModelMessage]]:
    """Async variant of ``resume_run_sync``."""
    from initrunner.agent.executor import execute_run_resume_async

    state = load_pending_state(audit_logger, run_id)
    if state is None:
        raise ValueError(f"No unresolved approvals found for run {run_id!r}")
    message_history, pending_rows = state
    missing = [row.tool_call_id for row in pending_rows if row.tool_call_id not in approvals]
    if missing:
        raise ValueError(f"Missing decisions for tool_call_ids: {missing}")

    result, new_messages = await execute_run_resume_async(
        agent,
        role,
        run_id=run_id,
        message_history=message_history,
        approvals=approvals,
        audit_logger=audit_logger,
        model_override=model_override,
        principal_id=principal_id,
    )
    for tool_call_id, decision in approvals.items():
        audit_logger.resolve_pending_approval(
            run_id=run_id,
            tool_call_id=tool_call_id,
            decision=decision,
            resolved_by=resolved_by,
        )
    if result.status == "paused":
        persist_paused_run(audit_logger, result, role, new_messages, role_path=role_path)
    return result, new_messages


async def execute_run_stream_async(
    agent: Agent,
    role: RoleDefinition,
    prompt: str | UserPrompt,
    *,
    audit_logger: AuditLogger | None = None,
    message_history: list[ModelMessage] | None = None,
    model_override: Model | str | None = None,
    on_token: Callable[[str], None] | None = None,
    on_partial: Callable[[Any], None] | None = None,
    on_event: Callable[[Any], None] | None = None,
    skip_input_validation: bool = False,
    principal_id: str | None = None,
) -> tuple[RunResult, list[ModelMessage]]:
    """Execute a streaming agent run (async).

    ``on_event`` receives typed ``AgentStreamEvent`` instances from
    ``agent.run_stream_events()``. When set, it takes precedence over the
    token/partial callbacks (both still fire for compatibility). When unset,
    the executor falls back to ``async with agent.run_stream(...)`` and
    routes text deltas to ``on_token`` or validated partials to
    ``on_partial`` depending on the role's output type.
    """
    from initrunner.agent.executor import execute_run_stream_async as _stream_async

    return await _stream_async(
        agent,
        role,
        prompt,
        audit_logger=audit_logger,
        message_history=message_history,
        model_override=model_override,
        on_token=on_token,
        on_partial=on_partial,
        on_event=on_event,
        skip_input_validation=skip_input_validation,
        principal_id=principal_id,
    )
