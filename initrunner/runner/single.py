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
    with console.status("Thinking...", spinner="dots"):
        result, messages = execute_run(
            agent,
            role,
            prompt,
            audit_logger=audit_logger,
            message_history=message_history,
            model_override=model_override,
        )
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

    from initrunner.agent.executor import execute_run_stream

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
        )
    finally:
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
