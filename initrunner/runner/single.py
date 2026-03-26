"""Single-shot runner: execute one prompt and display the result."""

from __future__ import annotations

from pydantic_ai import Agent
from pydantic_ai.models import Model

from initrunner.agent.executor import RunResult, execute_run
from initrunner.agent.prompt import UserPrompt, extract_text_from_prompt
from initrunner.agent.schema.role import RoleDefinition
from initrunner.audit.logger import AuditLogger
from initrunner.runner.display import _display_result, _display_stream_stats, console
from initrunner.sinks.dispatcher import SinkDispatcher


def _build_single_shot_extras(role: RoleDefinition) -> list | None:
    """Build run-scoped toolsets for single-shot mode, if any are configured."""
    from initrunner.agent.reflection import ReflectionState
    from initrunner.agent.tools._registry import is_run_scoped

    has_run_scoped = any(is_run_scoped(t.type) for t in role.spec.tools)
    if not has_run_scoped:
        return None

    from initrunner.runner.reasoning import build_run_scoped_toolsets

    return build_run_scoped_toolsets(role, ReflectionState())


def _get_clarify_timeout(role: RoleDefinition) -> float | None:
    """Return the clarify tool timeout if configured, else ``None``."""
    from initrunner.agent.schema.tools import ClarifyToolConfig

    for tool in role.spec.tools:
        if isinstance(tool, ClarifyToolConfig):
            return float(tool.timeout_seconds)
    return None


def run_single(
    agent: Agent,
    role: RoleDefinition,
    prompt: UserPrompt,
    *,
    audit_logger: AuditLogger | None = None,
    message_history: list | None = None,
    sink_dispatcher: SinkDispatcher | None = None,
    model_override: Model | str | None = None,
) -> tuple[RunResult, list]:
    """Execute a single prompt and display the result."""
    from initrunner.agent.clarify import (
        make_cli_clarify_callback,
        reset_clarify_callback,
        set_clarify_callback,
    )
    from initrunner.agent.tool_events import reset_tool_event_callback, set_tool_event_callback
    from initrunner.runner.display import _make_tool_event_printer

    extra_toolsets = _build_single_shot_extras(role)
    token = set_tool_event_callback(_make_tool_event_printer())
    clarify_timeout = _get_clarify_timeout(role)
    clarify_token = (
        set_clarify_callback(make_cli_clarify_callback(timeout=clarify_timeout))
        if clarify_timeout is not None
        else None
    )
    try:
        with console.status("Thinking...", spinner="dots"):
            result, messages = execute_run(
                agent,
                role,
                prompt,
                audit_logger=audit_logger,
                message_history=message_history,
                model_override=model_override,
                extra_toolsets=extra_toolsets,
            )
    finally:
        if clarify_token is not None:
            reset_clarify_callback(clarify_token)
        reset_tool_event_callback(token)
    _display_result(result)
    if sink_dispatcher is not None:
        sink_dispatcher.dispatch(result, extract_text_from_prompt(prompt))
    return result, messages


def run_single_stream(
    agent: Agent,
    role: RoleDefinition,
    prompt: UserPrompt,
    *,
    audit_logger: AuditLogger | None = None,
    message_history: list | None = None,
    sink_dispatcher: SinkDispatcher | None = None,
    model_override: Model | str | None = None,
) -> tuple[RunResult, list]:
    """Execute a single prompt with streaming output to the console."""
    # Fall back to buffered mode for non-text output types
    if role.spec.output.type != "text":
        return run_single(
            agent,
            role,
            prompt,
            audit_logger=audit_logger,
            message_history=message_history,
            sink_dispatcher=sink_dispatcher,
            model_override=model_override,
        )

    from initrunner.agent.clarify import (
        make_cli_clarify_callback,
        reset_clarify_callback,
        set_clarify_callback,
    )
    from initrunner.agent.executor import execute_run_stream
    from initrunner.agent.tool_events import reset_tool_event_callback, set_tool_event_callback
    from initrunner.runner.display import _make_tool_event_printer

    extra_toolsets = _build_single_shot_extras(role)
    cb_token = set_tool_event_callback(_make_tool_event_printer())
    clarify_timeout = _get_clarify_timeout(role)
    clarify_token = (
        set_clarify_callback(make_cli_clarify_callback(timeout=clarify_timeout))
        if clarify_timeout is not None
        else None
    )

    out = console.file
    status = console.status("Thinking...", spinner="dots")
    status.start()
    first_token = True

    def on_token(chunk: str) -> None:
        nonlocal first_token
        if first_token:
            status.stop()
            first_token = False
        out.write(chunk)
        out.flush()

    try:
        result, messages = execute_run_stream(
            agent,
            role,
            prompt,
            audit_logger=audit_logger,
            message_history=message_history,
            model_override=model_override,
            on_token=on_token,
            extra_toolsets=extra_toolsets,
        )
    finally:
        if clarify_token is not None:
            reset_clarify_callback(clarify_token)
        reset_tool_event_callback(cb_token)
        if first_token:
            status.stop()

    # Ensure a newline separates streamed output from follow-up UI
    out.write("\n")
    out.flush()

    if result.success:
        _display_stream_stats(result)
    else:
        _display_result(result)

    if sink_dispatcher is not None:
        sink_dispatcher.dispatch(result, extract_text_from_prompt(prompt))
    return result, messages
