"""Autonomous agentic loop runner."""

from __future__ import annotations

import logging
import time

from pydantic_ai import Agent
from pydantic_ai.models import Model

from initrunner.agent.executor import (
    AutonomousResult,
    ErrorCategory,
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

    # Derive error_category from the autonomous exit reason.
    error_category: ErrorCategory | None = None
    if final_status == "error" and iterations:
        error_category = iterations[-1].error_category
    elif final_status == "timeout":
        error_category = ErrorCategory.TIMEOUT
    elif final_status == "budget_exceeded":
        error_category = ErrorCategory.USAGE_LIMIT

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
        error_category=error_category,
    )


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
    from initrunner.agent.reflection import ReflectionState
    from initrunner.runner.reasoning import (
        build_run_scoped_toolsets,
        resolve_strategy,
    )
    from initrunner.triggers.base import CONVERSATIONAL_TRIGGER_TYPES

    autonomous_run_id = generate_id()
    autonomy_config = role.spec.autonomy or AutonomyConfig()
    guardrails = role.spec.guardrails
    max_iterations = max_iterations_override or guardrails.max_iterations
    token_budget = guardrails.autonomous_token_budget

    # Unified state + strategy
    reflection_state = ReflectionState()
    strategy = resolve_strategy(role.spec.reasoning, role)

    # Build run-scoped toolsets (todo, think, spawn, finish_task)
    run_scoped = build_run_scoped_toolsets(role, reflection_state, autonomy_config)

    # Strategy-specific toolsets (e.g., finalize_plan for plan_execute)
    strategy_toolsets = strategy.build_strategy_toolsets(reflection_state)

    all_extra = list(run_scoped) + strategy_toolsets
    if extra_toolsets:
        all_extra.extend(extra_toolsets)

    session_id = generate_id()
    consecutive_no_tool_calls = 0
    cumulative_tokens = 0
    iterations: list[RunResult] = []
    final_status = "completed"
    error_msg: str | None = None
    loop_start = time.monotonic()

    from initrunner.agent.clarify import (
        make_cli_clarify_callback,
        reset_clarify_callback,
        set_clarify_callback,
    )
    from initrunner.agent.tool_events import reset_tool_event_callback, set_tool_event_callback
    from initrunner.runner.display import _make_tool_event_printer

    cb_token = set_tool_event_callback(_make_tool_event_printer())

    from initrunner.agent.schema.tools import ClarifyToolConfig

    clarify_timeout = next(
        (float(t.timeout_seconds) for t in role.spec.tools if isinstance(t, ClarifyToolConfig)),
        None,
    )
    clarify_token = (
        set_clarify_callback(make_cli_clarify_callback(timeout=clarify_timeout))
        if clarify_timeout is not None
        else None
    )

    _display_autonomous_header(role, max_iterations, token_budget)

    autonomous_timeout = guardrails.autonomous_timeout_seconds

    from rich.progress import (
        BarColumn,
        MofNCompleteColumn,
        Progress,
        SpinnerColumn,
        TextColumn,
        TimeElapsedColumn,
    )

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        ptask = progress.add_task("Autonomous run", total=max_iterations)

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
                    console.print(
                        "[dim]Hint:[/dim] Increase"
                        " [bold]guardrails.autonomous_token_budget[/bold]"
                        " or reduce [bold]max_iterations[/bold]."
                    )
                    break

            # Build prompt via strategy
            if iteration == 1:
                iter_prompt = strategy.wrap_initial_prompt(prompt)
            else:
                iter_prompt = strategy.build_continuation_prompt(reflection_state)

                # Stronger nudge for messaging triggers when agent didn't use tools
                if consecutive_no_tool_calls > 0 and trigger_type in CONVERSATIONAL_TRIGGER_TYPES:
                    iter_prompt += (
                        "\n\nIMPORTANT: You did not use any tools in your last response. "
                        "If you cannot proceed without additional user input, call "
                        "finish_task(summary='...', status='blocked') immediately. "
                        "Do NOT repeat your question -- the user will send a new message."
                    )

            # Execute iteration
            t_meta = dict(trigger_metadata or {})
            t_meta["autonomous_run_id"] = autonomous_run_id
            t_meta["iteration"] = str(iteration)

            progress.update(ptask, description=f"Iteration {iteration}/{max_iterations}")
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
            progress.update(ptask, advance=1)

            iterations.append(result)
            cumulative_tokens += result.total_tokens
            message_history = new_messages

            # Update budget state so the next continuation prompt reflects
            # completed work (iterations, tokens, elapsed time).
            reflection_state.iterations_completed = iteration
            reflection_state.max_iterations = max_iterations
            reflection_state.tokens_consumed = cumulative_tokens
            reflection_state.token_budget = token_budget
            reflection_state.elapsed_seconds = time.monotonic() - loop_start
            reflection_state.timeout_seconds = autonomous_timeout

            _display_iteration_result(
                result, iteration, max_iterations, cumulative_tokens, token_budget
            )

            # Compact then trim history
            if message_history:
                from initrunner.agent.history import reduce_history

                message_history = reduce_history(
                    message_history, autonomy_config, role, preserve_first=True
                )

            # Check strategy-driven completion
            if not strategy.should_continue(reflection_state, iteration):
                final_status = reflection_state.status
                break

            # Check for errors
            if not result.success:
                final_status = "error"
                error_msg = result.error
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

    if clarify_token is not None:
        reset_clarify_callback(clarify_token)
    reset_tool_event_callback(cb_token)

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
        from initrunner.agent.memory_capture import capture_episode

        capture_episode(memory_store, role, reflection_state.summary, category="autonomous_run")

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
