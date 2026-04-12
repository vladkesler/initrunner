"""Validation, output processing, audit logging, and observability for agent execution."""

from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from typing import Any

from pydantic import BaseModel
from pydantic_ai.exceptions import ModelHTTPError, UsageLimitExceeded

from initrunner.agent.prompt import UserPrompt, attachment_summary, extract_text_from_prompt
from initrunner.agent.schema.role import RoleDefinition
from initrunner.audit.logger import AuditLogger, AuditRecord

from .executor_models import ErrorCategory, RunResult

_logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Input / output validation
# ---------------------------------------------------------------------------


def _validate_input_or_fail(
    prompt: UserPrompt,
    role: RoleDefinition,
    run_id: str,
    *,
    audit_logger: AuditLogger | None = None,
    model_override: Any = None,
    trigger_type: str | None = None,
    trigger_metadata: dict[str, str] | None = None,
    principal_id: str | None = None,
) -> RunResult | None:
    """Run pre-flight content validation. Returns a failed RunResult if blocked, else None."""
    from initrunner.agent.policies import redact_text, validate_input

    prompt_text = extract_text_from_prompt(prompt)
    content_policy = role.spec.security.content
    validation = validate_input(prompt_text, content_policy, model_override=model_override)
    if not validation.valid:
        result = RunResult(run_id=run_id, success=False, error=validation.reason, duration_ms=0)
        if audit_logger is not None:
            audit_prompt = redact_text(prompt_text, content_policy)
            audit_logger.log(
                AuditRecord.from_run(
                    result,
                    role,
                    audit_prompt,
                    trigger_type=trigger_type,
                    trigger_metadata=trigger_metadata,
                    principal_id=principal_id,
                )
            )
        return result
    return None


def _handle_run_error(
    result: RunResult,
    exc: Exception,
    partial_output: str = "",
    *,
    timeout_seconds: float | None = None,
) -> None:
    """Populate *result* fields for a caught run-time exception.

    When *timeout_seconds* is provided and *exc* is a ``TimeoutError``
    with an empty message (as from ``asyncio.wait_for``), the error
    string is formatted using the timeout value.
    """
    result.success = False
    if isinstance(exc, ModelHTTPError):
        result.error = f"Model API error: {exc}"
        if exc.status_code == 429:
            result.error_category = ErrorCategory.RATE_LIMIT
        elif exc.status_code in {401, 403}:
            result.error_category = ErrorCategory.AUTH
        elif exc.status_code in {500, 502, 503, 504}:
            result.error_category = ErrorCategory.SERVER_ERROR
        else:
            result.error_category = ErrorCategory.UNKNOWN
    elif isinstance(exc, UsageLimitExceeded):
        result.error = f"Usage limit exceeded: {exc}"
        result.error_category = ErrorCategory.USAGE_LIMIT
    elif isinstance(exc, TimeoutError):
        result.error_category = ErrorCategory.TIMEOUT
        if not str(exc) and timeout_seconds is not None:
            result.error = f"TimeoutError: Run timed out after {int(timeout_seconds)}s"
        else:
            result.error = f"TimeoutError: {exc}"
    elif isinstance(exc, (ConnectionError, OSError)):
        result.error = f"{type(exc).__name__}: {exc}"
        result.error_category = ErrorCategory.CONNECTION
    else:
        result.error = f"{type(exc).__name__}: {exc}"
        result.error_category = ErrorCategory.UNKNOWN
    if partial_output:
        result.output = partial_output


def _apply_output_validation(result: RunResult, role: RoleDefinition) -> None:
    """Apply post-run output validation and mutation in-place."""
    from initrunner.agent.policies import validate_output

    content_policy = role.spec.security.content
    output_result = validate_output(result.output, content_policy)
    if output_result.blocked:
        result.success = False
        result.error = output_result.reason
        result.output = ""
    else:
        result.output = output_result.text


# ---------------------------------------------------------------------------
# Audit logging
# ---------------------------------------------------------------------------


def _audit_result(
    result: RunResult,
    role: RoleDefinition,
    prompt: UserPrompt,
    *,
    audit_logger: AuditLogger | None,
    trigger_type: str | None = None,
    trigger_metadata: dict[str, str] | None = None,
    principal_id: str | None = None,
) -> None:
    """Log result to audit trail if a logger is provided."""
    if audit_logger is None:
        return
    from initrunner.agent.policies import redact_text

    prompt_text = extract_text_from_prompt(prompt)
    summary = attachment_summary(prompt)
    content_policy = role.spec.security.content
    audit_prompt = redact_text(prompt_text, content_policy)
    if summary:
        audit_prompt = f"{audit_prompt} {summary}"
    audit_output = redact_text(result.output, content_policy)
    audit_logger.log(
        AuditRecord.from_run(
            result,
            role,
            audit_prompt,
            output_override=audit_output,
            trigger_type=trigger_type,
            trigger_metadata=trigger_metadata,
            principal_id=principal_id,
        )
    )


# ---------------------------------------------------------------------------
# Output processing (deduplicates sync/async paths)
# ---------------------------------------------------------------------------


def _extract_tool_call_names(messages: list) -> list[str]:
    """Extract tool call names from message history."""
    from pydantic_ai.messages import ModelResponse, ToolCallPart

    return [
        part.tool_name
        for msg in messages
        if isinstance(msg, ModelResponse)
        for part in msg.parts
        if isinstance(part, ToolCallPart)
    ]


def _process_agent_output(agent_result: Any, result: RunResult, role: RoleDefinition) -> list:
    """Serialize agent output, validate, extract usage. Returns new_messages."""
    raw_output = agent_result.output
    if isinstance(raw_output, BaseModel):
        result.output = raw_output.model_dump_json()
    elif isinstance(raw_output, (dict, list)):
        result.output = json.dumps(raw_output)
    else:
        result.output = str(raw_output)

    _apply_output_validation(result, role)

    usage = agent_result.usage()
    result.tokens_in = usage.input_tokens or 0
    result.tokens_out = usage.output_tokens or 0
    result.total_tokens = usage.total_tokens or 0
    result.tool_calls = usage.tool_calls or 0
    new_messages = agent_result.all_messages()
    result.tool_call_names = _extract_tool_call_names(new_messages)
    return new_messages


def _process_stream_output(
    output_parts: list[str],
    usage: Any,
    new_messages: list,
    result: RunResult,
    role: RoleDefinition,
) -> None:
    """Finalize stream output: join parts, validate, extract usage."""
    result.tool_call_names = _extract_tool_call_names(new_messages)
    result.output = "".join(output_parts)
    _apply_output_validation(result, role)

    if usage is not None:
        result.tokens_in = usage.input_tokens or 0
        result.tokens_out = usage.output_tokens or 0
        result.total_tokens = usage.total_tokens or 0
        result.tool_calls = usage.tool_calls or 0


# ---------------------------------------------------------------------------
# Observability
# ---------------------------------------------------------------------------


def _record_span_metrics(span: Any, result: RunResult) -> None:
    """Set standard OpenTelemetry span attributes from a RunResult."""
    span.set_attribute("initrunner.tokens_total", result.total_tokens)
    span.set_attribute("initrunner.duration_ms", result.duration_ms)
    span.set_attribute("initrunner.success", result.success)


@contextmanager
def _create_run_span(run_id: str, role: RoleDefinition, trigger_type: str | None = None):
    """Create an OpenTelemetry span with standard agent-run attributes."""
    from opentelemetry import trace  # type: ignore[import-not-found]

    tracer = trace.get_tracer("initrunner")
    with tracer.start_as_current_span(
        "initrunner.agent.run",
        attributes={
            "initrunner.run_id": run_id,
            "initrunner.agent_name": role.metadata.name,
            "initrunner.trigger_type": trigger_type or "",
        },
    ) as span:
        yield span
