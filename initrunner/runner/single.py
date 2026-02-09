"""Single-shot runner: execute one prompt and display the result."""

from __future__ import annotations

from pydantic_ai import Agent
from pydantic_ai.models import Model

from initrunner.agent.executor import RunResult, execute_run
from initrunner.agent.schema import RoleDefinition
from initrunner.audit.logger import AuditLogger
from initrunner.runner.display import _display_result, console
from initrunner.sinks.dispatcher import SinkDispatcher


def run_single(
    agent: Agent,
    role: RoleDefinition,
    prompt: str,
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
        sink_dispatcher.dispatch(result, prompt)
    return result, messages
