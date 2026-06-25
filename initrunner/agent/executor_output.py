"""Validation, output processing, audit logging, and observability for agent execution."""

from __future__ import annotations

import json
import logging
import time
from contextlib import contextmanager
from typing import Any

from pydantic import BaseModel
from pydantic_ai.exceptions import ModelHTTPError, UsageLimitExceeded
from pydantic_ai.models.fallback import FallbackExceptionGroup

from initrunner.agent.prompt import UserPrompt, attachment_summary, extract_text_from_prompt
from initrunner.agent.schema.role import RoleDefinition
from initrunner.audit._redact import scrub_secrets
from initrunner.audit.logger import AuditLogger, AuditRecord

from .executor_models import ErrorCategory, PendingApproval, RunResult

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


def _classify_single_exception(exc: BaseException) -> ErrorCategory:
    """Map one exception to an ErrorCategory using the same rules as _handle_run_error."""
    if isinstance(exc, ModelHTTPError):
        if exc.status_code == 429:
            return ErrorCategory.RATE_LIMIT
        if exc.status_code in {401, 403}:
            return ErrorCategory.AUTH
        if exc.status_code in {500, 502, 503, 504}:
            return ErrorCategory.SERVER_ERROR
        return ErrorCategory.UNKNOWN
    if isinstance(exc, UsageLimitExceeded):
        return ErrorCategory.USAGE_LIMIT
    if isinstance(exc, TimeoutError):
        return ErrorCategory.TIMEOUT
    if isinstance(exc, (ConnectionError, OSError)):
        return ErrorCategory.CONNECTION
    return ErrorCategory.UNKNOWN


def _format_inner_failure(exc: BaseException) -> str:
    """Short, operator-facing summary of one provider's failure."""
    if isinstance(exc, ModelHTTPError):
        return f"{exc.model_name} HTTP {exc.status_code}"
    return f"{type(exc).__name__}: {exc}"


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
    if isinstance(exc, FallbackExceptionGroup):
        # Every candidate in the FallbackModel chain failed. Classify by the
        # last inner exception -- that is the one that actually terminated
        # the chain -- and list every failure in the error string so the
        # operator can see the full picture.
        inner = list(exc.exceptions)
        last = inner[-1] if inner else exc
        result.error_category = _classify_single_exception(last)
        summaries = ", ".join(_format_inner_failure(e) for e in inner)
        result.error = f"All {len(inner)} fallback models failed: [{summaries}]"
    elif isinstance(exc, ModelHTTPError):
        result.error = f"Model API error: {exc}"
        result.error_category = _classify_single_exception(exc)
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


_THINKING_DETAIL_KEYS = ("thinking_tokens", "reasoning_tokens")


def _extract_thinking_tokens(usage: Any) -> int:
    """Return the thinking/reasoning token count from a pydantic_ai usage object.

    Handles both a direct ``thinking_tokens`` attribute (should a future
    pydantic_ai release add one) and the current shape, where OpenAI reasoning
    tokens surface inside the ``details`` dict under ``reasoning_tokens``.
    Returns 0 when no such count is present.
    """
    direct = getattr(usage, "thinking_tokens", None)
    if direct:
        return int(direct)
    details = getattr(usage, "details", None)
    if isinstance(details, dict):
        for key in _THINKING_DETAIL_KEYS:
            value = details.get(key)
            if value:
                return int(value)
    return 0


def _extract_reasoning_tokens(usage: Any) -> int:
    """Return the reasoning token count from a usage object, else 0.

    Alias of ``_extract_thinking_tokens`` kept as a named entry point for the
    streaming consumer, which talks about "reasoning tokens" to match the
    pydantic_ai event vocabulary. Both surface the same underlying count.
    """
    return _extract_thinking_tokens(usage)


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


# ---------------------------------------------------------------------------
# Streaming event timeline (redacted, best-effort observability log)
# ---------------------------------------------------------------------------

# Cap so a long-running agent with many tool calls cannot grow an unbounded
# timeline. We keep the most recent entries (the tail), which is where the
# interesting failures tend to be.
_TIMELINE_MAX_ENTRIES = 500


def _now_ms() -> int:
    """Wall-clock milliseconds for timeline ordering. Best-effort, monotonic-ish."""
    return int(time.time() * 1000)


def _truncate_redact(text: str | None, max_len: int) -> str | None:
    """Secret-scrub then length-bound a free-text preview for the timeline."""
    if not text:
        return None
    scrubbed = scrub_secrets(text)
    if len(scrubbed) > max_len:
        return scrubbed[:max_len] + "[truncated]"
    return scrubbed


def _preview_args(args: Any, max_len: int) -> str | None:
    """Render tool-call args (dict or JSON string) to a redacted preview."""
    if args is None:
        return None
    rendered = json.dumps(args, default=str) if isinstance(args, dict) else str(args)
    return _truncate_redact(rendered, max_len)


def build_timeline_entry(event: Any) -> dict[str, Any] | None:
    """Map a typed ``AgentStreamEvent`` to a redacted plain-dict timeline entry.

    Returns ``None`` for events we do not record (text deltas, start/end
    markers). Every returned dict is JSON-serializable and secret-scrubbed,
    so it is safe to persist in the audit trail. Never raises -- a malformed
    event yields ``None`` rather than crashing the stream.
    """
    from pydantic_ai.messages import (
        FunctionToolCallEvent,
        FunctionToolResultEvent,
        OutputToolCallEvent,
        OutputToolResultEvent,
        PartDeltaEvent,
        ThinkingPartDelta,
        ToolCallPartDelta,
    )

    try:
        if isinstance(event, PartDeltaEvent):
            delta = event.delta
            if isinstance(delta, ThinkingPartDelta):
                return {
                    "type": "thinking_delta",
                    "timestamp_unix_ms": _now_ms(),
                    "content_delta": _truncate_redact(delta.content_delta, 200),
                    "has_signature": delta.signature_delta is not None,
                    "provider_name": delta.provider_name,
                }
            if isinstance(delta, ToolCallPartDelta):
                return {
                    "type": "tool_call_delta",
                    "timestamp_unix_ms": _now_ms(),
                    "tool_call_id": delta.tool_call_id,
                    "tool_name_delta": delta.tool_name_delta,
                    "args_delta_preview": _preview_args(delta.args_delta, 120),
                }
            return None
        if isinstance(event, FunctionToolCallEvent):
            part = event.part
            return {
                "type": "function_tool_call",
                "timestamp_unix_ms": _now_ms(),
                "tool_call_id": part.tool_call_id,
                "tool_name": part.tool_name,
                "args_preview": _preview_args(part.args, 120),
                "args_valid": event.args_valid,
            }
        if isinstance(event, FunctionToolResultEvent):
            content = event.content
            content_preview = _truncate_redact(content, 120) if isinstance(content, str) else None
            part_type = type(event.part).__name__ if event.part is not None else None
            return {
                "type": "function_tool_result",
                "timestamp_unix_ms": _now_ms(),
                "content_preview": content_preview,
                "part_type": part_type,
            }
        if isinstance(event, OutputToolCallEvent):
            part = event.part
            return {
                "type": "output_tool_call",
                "timestamp_unix_ms": _now_ms(),
                "tool_call_id": part.tool_call_id,
                "tool_name": part.tool_name,
                "args_preview": _preview_args(part.args, 120),
                "args_valid": event.args_valid,
            }
        if isinstance(event, OutputToolResultEvent):
            # OutputToolResultEvent carries no event-level ``content`` (unlike
            # FunctionToolResultEvent); the result payload lives on the part.
            part = event.part
            content = getattr(part, "content", None)
            content_preview = _truncate_redact(content, 120) if isinstance(content, str) else None
            part_type = type(part).__name__ if part is not None else None
            return {
                "type": "output_tool_result",
                "timestamp_unix_ms": _now_ms(),
                "content_preview": content_preview,
                "part_type": part_type,
            }
    except Exception:
        # Timeline is best-effort observability; never let it break the run.
        return None
    return None


def build_timeline_from_messages(messages: list) -> list[dict[str, Any]]:
    """Reconstruct a redacted timeline from a run's final message history.

    Used by the buffered (non-streaming) path and the streaming path's
    ``run_stream()`` backbone, which never see live ``AgentStreamEvent``
    instances. Walks messages in order, emitting the same entry shapes
    ``build_timeline_entry`` produces for live events:

    - ``ThinkingPart``     -> ``thinking_delta`` entry
    - ``ToolCallPart``     -> ``function_tool_call`` entry
    - ``ToolReturnPart``   -> ``function_tool_result`` entry

    Every free-text value is secret-scrubbed and length-bounded. Never
    raises -- a malformed message yields no entry rather than crashing the
    run. The result is uncapped here; callers run it through ``cap_timeline``.
    """
    from pydantic_ai.messages import (
        ModelRequest,
        ModelResponse,
        ThinkingPart,
        ToolCallPart,
        ToolReturnPart,
    )

    timeline: list[dict[str, Any]] = []
    for message in messages:
        try:
            parts = getattr(message, "parts", None)
            if not parts:
                continue
            # Tool calls and thinking originate in model responses; tool
            # returns come back in the following request. Emitting in message
            # order keeps call-then-result adjacency in the timeline.
            if isinstance(message, ModelResponse):
                for part in parts:
                    if isinstance(part, ThinkingPart):
                        timeline.append(
                            {
                                "type": "thinking_delta",
                                "timestamp_unix_ms": _now_ms(),
                                "content_delta": _truncate_redact(part.content, 200),
                                "has_signature": part.signature is not None,
                                "provider_name": part.provider_name,
                            }
                        )
                    elif isinstance(part, ToolCallPart):
                        timeline.append(
                            {
                                "type": "function_tool_call",
                                "timestamp_unix_ms": _now_ms(),
                                "tool_call_id": part.tool_call_id,
                                "tool_name": part.tool_name,
                                "args_preview": _preview_args(part.args, 120),
                                "args_valid": True,
                            }
                        )
            elif isinstance(message, ModelRequest):
                for part in parts:
                    if isinstance(part, ToolReturnPart):
                        content = part.content
                        content_preview = (
                            _truncate_redact(content, 120) if isinstance(content, str) else None
                        )
                        timeline.append(
                            {
                                "type": "function_tool_result",
                                "timestamp_unix_ms": _now_ms(),
                                "content_preview": content_preview,
                                "part_type": type(part).__name__,
                            }
                        )
        except Exception:
            # Timeline is best-effort observability; never let it break the run.
            continue
    return timeline


def cap_timeline(timeline: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Bound timeline length, keeping the most recent entries."""
    if len(timeline) > _TIMELINE_MAX_ENTRIES:
        return timeline[-_TIMELINE_MAX_ENTRIES:]
    return timeline


def _finalize_run_output(
    raw_output: Any,
    usage: Any,
    new_messages: list,
    result: RunResult,
    role: RoleDefinition,
    *,
    reasoning_tokens: int | None = None,
    event_timeline: list[dict[str, Any]] | None = None,
    capture_timeline: bool = False,
) -> list:
    """Finalize a run: serialize output, validate, extract usage, extract tool names.

    Shared between streaming (sync + async) and non-streaming paths. Accepts
    unpacked components so the streaming path can source them from a
    ``StreamedRunResult`` / final ``AgentRunResultEvent``.

    The streaming consumer may pass a ``reasoning_tokens`` count extracted from
    the final event and an ``event_timeline`` of redacted thinking/tool entries;
    both are attached to ``result`` for cost tracking and audit logging.

    When ``capture_timeline`` is set and no live ``event_timeline`` was
    supplied (the buffered path and the non-``on_event`` streaming path never
    see live stream events), the timeline is reconstructed from
    ``new_messages`` so a CLI run still records a meaningful tool-call/result
    trace. Callers gate this on audit being enabled so non-audited runs add no
    overhead.
    """
    from pydantic_ai import DeferredToolRequests

    if isinstance(raw_output, DeferredToolRequests):
        # Human-in-the-loop pause: the model asked to call tools whose
        # ``approval: required`` config gates them behind ApprovalRequired.
        # Capture each pending ToolCallPart verbatim — the caller resolves
        # them via execute_run_resume() with DeferredToolResults.
        result.status = "paused"
        result.pending_approvals = [
            PendingApproval(
                tool_call_id=call.tool_call_id,
                tool_name=call.tool_name,
                arguments=_coerce_args_to_dict(call.args),
            )
            for call in raw_output.approvals
        ]
        result.output = ""
    else:
        if isinstance(raw_output, BaseModel):
            result.output = raw_output.model_dump_json()
        elif isinstance(raw_output, (dict, list)):
            result.output = json.dumps(raw_output)
        else:
            result.output = str(raw_output)
        _apply_output_validation(result, role)

    if usage is not None:
        result.tokens_in = usage.input_tokens or 0
        result.tokens_out = usage.output_tokens or 0
        result.total_tokens = usage.total_tokens or 0
        result.thinking_tokens = _extract_thinking_tokens(usage)
        result.tool_calls = usage.tool_calls or 0
    result.reasoning_tokens = (
        reasoning_tokens if reasoning_tokens is not None else _extract_reasoning_tokens(usage)
    )
    if event_timeline is not None:
        result.event_timeline = cap_timeline(event_timeline)
    elif capture_timeline:
        result.event_timeline = cap_timeline(build_timeline_from_messages(new_messages))
    result.tool_call_names = _extract_tool_call_names(new_messages)
    return new_messages


def _process_agent_output(
    agent_result: Any,
    result: RunResult,
    role: RoleDefinition,
    *,
    capture_timeline: bool = False,
) -> list:
    """Serialize agent output, validate, extract usage. Returns new_messages.

    With ``capture_timeline`` set, reconstructs the redacted event timeline
    from the run's messages so a buffered (non-streaming) run still records a
    tool-call/result trace. Callers gate this on audit being enabled.
    """
    return _finalize_run_output(
        agent_result.output,
        agent_result.usage,
        agent_result.all_messages(),
        result,
        role,
        capture_timeline=capture_timeline,
    )


def _coerce_args_to_dict(args: Any) -> dict[str, Any]:
    """Normalize a ToolCallPart.args into a plain dict for persistence.

    PydanticAI hands us either a JSON string (most providers) or a dict
    (structured providers). Both shapes round-trip through json.dumps, so
    we normalize to dict here to keep downstream consumers simple.
    """
    if isinstance(args, dict):
        return args
    if isinstance(args, str):
        try:
            parsed = json.loads(args)
        except json.JSONDecodeError:
            return {"_raw": args}
        return parsed if isinstance(parsed, dict) else {"_value": parsed}
    return {"_value": args}


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
