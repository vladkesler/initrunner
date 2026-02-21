"""Autonomous agentic loop runner."""

from __future__ import annotations

import logging
import time

from pydantic_ai import Agent
from pydantic_ai.models import Model

from initrunner.agent.executor import (
    AutonomousResult,
    RunResult,
    check_token_budget,
    execute_run,
)
from initrunner.agent.memory_ops import save_session
from initrunner.agent.prompt import UserPrompt, extract_text_from_prompt
from initrunner.agent.schema.autonomy import AutonomyConfig
from initrunner.agent.schema.role import RoleDefinition
from initrunner.audit.logger import AuditLogger
from initrunner.runner.display import (
    _display_autonomous_header,
    _display_autonomous_summary,
    _display_iteration_result,
    _display_save_warning,
    console,
)
from initrunner.sinks.dispatcher import SinkDispatcher
from initrunner.stores.base import MemoryStoreBase

_logger = logging.getLogger(__name__)


def _build_autonomous_result(
    autonomous_run_id: str,
    iterations: list[RunResult],
    cumulative_tokens: int,
    final_status: str,
    error_msg: str | None,
    reflection_summary: str | None,
    total_duration: int,
) -> AutonomousResult:
    """Build the final AutonomousResult from accumulated iteration data."""
    final_output = iterations[-1].output if iterations else ""
    return AutonomousResult(
        run_id=autonomous_run_id,
        iterations=iterations,
        final_output=final_output,
        final_status=final_status,
        finish_summary=reflection_summary,
        total_tokens_in=sum(r.tokens_in for r in iterations),
        total_tokens_out=sum(r.tokens_out for r in iterations),
        total_tokens=cumulative_tokens,
        total_tool_calls=sum(r.tool_calls for r in iterations),
        total_duration_ms=total_duration,
        iteration_count=len(iterations),
        success=final_status in ("completed", "max_iterations"),
        error=error_msg,
    )


def _capture_autonomous_episode(
    memory_store: MemoryStoreBase,
    role: RoleDefinition,
    summary: str,
) -> None:
    """Persist the autonomous run summary as an episodic memory."""
    from initrunner.agent.memory_capture import capture_episode

    capture_episode(memory_store, role, summary, category="autonomous_run")


def run_autonomous(
    agent: Agent,
    role: RoleDefinition,
    prompt: UserPrompt,
    *,
    audit_logger: AuditLogger | None = None,
    sink_dispatcher: SinkDispatcher | None = None,
    memory_store: MemoryStoreBase | None = None,
    model_override: Model | str | None = None,
    max_iterations_override: int | None = None,
    extra_toolsets: list | None = None,
    trigger_type: str | None = None,
    trigger_metadata: dict[str, str] | None = None,
    message_history: list | None = None,
) -> AutonomousResult:
    """Execute an autonomous agentic loop until completion or budget exhaustion."""
    from initrunner._ids import generate_id
    from initrunner.agent.history import trim_message_history
    from initrunner.agent.reflection import ReflectionState, format_reflection_state
    from initrunner.agent.tools.reflection import build_reflection_toolset
    from initrunner.triggers.base import CONVERSATIONAL_TRIGGER_TYPES

    autonomous_run_id = generate_id()
    autonomy_config = role.spec.autonomy or AutonomyConfig()
    guardrails = role.spec.guardrails
    max_iterations = max_iterations_override or guardrails.max_iterations
    token_budget = guardrails.autonomous_token_budget

    reflection_state = ReflectionState()
    reflection_toolset = build_reflection_toolset(autonomy_config, reflection_state)

    all_extra = [reflection_toolset]
    if extra_toolsets:
        all_extra.extend(extra_toolsets)

    session_id = generate_id()
    consecutive_no_tool_calls = 0
    cumulative_tokens = 0
    iterations: list[RunResult] = []
    final_status = "completed"
    error_msg: str | None = None
    loop_start = time.monotonic()

    _display_autonomous_header(role, max_iterations, token_budget)

    autonomous_timeout = guardrails.autonomous_timeout_seconds

    for iteration in range(1, max_iterations + 1):
        # Check wall-clock timeout
        if autonomous_timeout is not None:
            elapsed = time.monotonic() - loop_start
            if elapsed >= autonomous_timeout:
                final_status = "timeout"
                console.print("[yellow]Autonomous wall-clock timeout reached.[/yellow]")
                break

        # Check token budget
        if token_budget is not None:
            budget_status = check_token_budget(cumulative_tokens, token_budget)
            if budget_status.exceeded:
                final_status = "budget_exceeded"
                console.print("[yellow]Autonomous token budget exhausted.[/yellow]")
                break

        # Build prompt
        if iteration == 1:
            iter_prompt = prompt
        else:
            state_text = format_reflection_state(reflection_state)
            iter_prompt = f"{autonomy_config.continuation_prompt}\n\nCURRENT STATUS:\n{state_text}"

            # Stronger nudge for messaging triggers when agent didn't use tools
            if consecutive_no_tool_calls > 0 and trigger_type in CONVERSATIONAL_TRIGGER_TYPES:
                iter_prompt += (
                    "\n\nIMPORTANT: You did not use any tools in your last response. "
                    "If you cannot proceed without additional user input, call "
                    "finish_task(summary='...', status='blocked') immediately. "
                    "Do NOT repeat your question — the user will send a new message."
                )

        # Execute iteration
        t_meta = dict(trigger_metadata or {})
        t_meta["autonomous_run_id"] = autonomous_run_id
        t_meta["iteration"] = str(iteration)

        with console.status(
            f"Thinking (iteration {iteration}/{max_iterations})...", spinner="dots"
        ):
            result, new_messages = execute_run(
                agent,
                role,
                iter_prompt,
                audit_logger=audit_logger,
                message_history=message_history,
                model_override=model_override,
                trigger_type=trigger_type or "autonomous",
                trigger_metadata=t_meta,
                extra_toolsets=all_extra,
            )

        iterations.append(result)
        cumulative_tokens += result.total_tokens
        message_history = new_messages

        _display_iteration_result(
            result, iteration, max_iterations, cumulative_tokens, token_budget
        )

        # Trim history
        if message_history:
            message_history = trim_message_history(
                message_history,
                autonomy_config.max_history_messages,
                preserve_first=True,
            )

        # Check if agent signalled completion
        if reflection_state.completed:
            final_status = reflection_state.status
            break

        # Check for errors
        if not result.success:
            final_status = "error"
            error_msg = result.error
            break

        # Conversational triggers: single iteration is sufficient — the agent
        # already had full tool access within this run.  Further iterations
        # would just produce a continuation prompt the user never asked for.
        if trigger_type in CONVERSATIONAL_TRIGGER_TYPES:
            final_status = "completed"
            break

        # Spin guard: stop if no tool calls for N consecutive iterations
        if result.tool_calls == 0:
            consecutive_no_tool_calls += 1
            if consecutive_no_tool_calls >= autonomy_config.max_no_tool_call_iterations:
                reflection_state.completed = True
                reflection_state.status = "blocked"
                reflection_state.summary = (
                    "Stopped: no tool calls for "
                    f"{consecutive_no_tool_calls} consecutive iterations."
                )
                final_status = "blocked"
                break
        else:
            consecutive_no_tool_calls = 0

        # Rate limiting
        if autonomy_config.iteration_delay_seconds > 0 and iteration < max_iterations:
            time.sleep(autonomy_config.iteration_delay_seconds)
    else:
        final_status = "max_iterations"

    total_duration = int((time.monotonic() - loop_start) * 1000)

    auto_result = _build_autonomous_result(
        autonomous_run_id,
        iterations,
        cumulative_tokens,
        final_status,
        error_msg,
        reflection_state.summary or None,
        total_duration,
    )

    # Save session for --resume
    if message_history and role.spec.memory is not None:
        if not save_session(role, session_id, message_history):
            _display_save_warning()

    # Persist final summary as an episodic memory
    if memory_store is not None and role.spec.memory is not None and reflection_state.summary:
        _capture_autonomous_episode(memory_store, role, reflection_state.summary)

    # Consolidation at session exit
    if memory_store is not None and role.spec.memory is not None:
        from initrunner.agent.memory_consolidation import maybe_consolidate

        if role.spec.memory.consolidation.interval in ("after_session", "after_autonomous"):
            maybe_consolidate(memory_store, role)

    # Dispatch to sinks (final output only)
    if sink_dispatcher is not None and iterations:
        sink_dispatcher.dispatch(iterations[-1], extract_text_from_prompt(prompt))

    auto_result.final_messages = message_history

    _display_autonomous_summary(
        auto_result, reflection_state.summary, max_iterations, cumulative_tokens
    )

    return auto_result
