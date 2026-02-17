"""Execute agent runs with guardrails and audit logging."""

from __future__ import annotations

import atexit
import json
import logging
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as _FuturesTimeout
from dataclasses import dataclass
from typing import Any, TypeVar

from pydantic_ai import Agent, UsageLimits
from pydantic_ai.exceptions import ModelHTTPError, UsageLimitExceeded
from pydantic_ai.models import Model

from initrunner._ids import generate_id
from initrunner.agent.prompt import UserPrompt, attachment_summary, extract_text_from_prompt
from initrunner.agent.schema import RoleDefinition
from initrunner.audit.logger import AuditLogger, AuditRecord

_logger = logging.getLogger(__name__)

_RETRY_MAX_ATTEMPTS = 3
_RETRY_BACKOFF_BASE = 1.0  # seconds
_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}

_TIMEOUT_POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix="run_timeout")
atexit.register(_TIMEOUT_POOL.shutdown, wait=False)


_T = TypeVar("_T")


def _run_with_timeout(fn: Callable[[], _T], timeout: float) -> _T:
    """Run *fn* in a thread pool with a hard timeout (seconds)."""
    future = _TIMEOUT_POOL.submit(fn)
    try:
        return future.result(timeout=timeout)
    except _FuturesTimeout:
        raise TimeoutError(f"Run timed out after {int(timeout)}s") from None


def _retry_model_call(
    fn: Callable[[], _T],
    *,
    on_retry: Callable[[], None] | None = None,
) -> _T:
    """Call *fn* with retry-on-transient-HTTP-error logic.

    Retries up to ``_RETRY_MAX_ATTEMPTS`` times for status codes in
    ``_RETRYABLE_STATUS_CODES``, using exponential backoff.  Calls
    *on_retry* (if provided) before each retry attempt.
    """
    last_http_error: ModelHTTPError | None = None
    for attempt in range(_RETRY_MAX_ATTEMPTS):
        try:
            return fn()
        except ModelHTTPError as e:
            if e.status_code not in _RETRYABLE_STATUS_CODES:
                raise
            last_http_error = e
            if on_retry is not None:
                on_retry()
            if attempt < _RETRY_MAX_ATTEMPTS - 1:
                delay = _RETRY_BACKOFF_BASE * (2**attempt)
                _logger.warning(
                    "Retryable HTTP %d from model (attempt %d/%d), retrying in %.1fs",
                    e.status_code,
                    attempt + 1,
                    _RETRY_MAX_ATTEMPTS,
                    delay,
                )
                time.sleep(delay)
    raise last_http_error  # type: ignore[misc]


@dataclass
class RunResult:
    run_id: str
    output: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    total_tokens: int = 0
    tool_calls: int = 0
    duration_ms: int = 0
    success: bool = True
    error: str | None = None


@dataclass
class AutonomousResult:
    run_id: str
    iterations: list[RunResult]
    final_output: str = ""
    final_status: str = "completed"
    finish_summary: str | None = None
    total_tokens_in: int = 0
    total_tokens_out: int = 0
    total_tokens: int = 0
    total_tool_calls: int = 0
    total_duration_ms: int = 0
    iteration_count: int = 0
    success: bool = True
    error: str | None = None


@dataclass
class TokenBudgetStatus:
    budget: int | None = None
    consumed: int = 0
    remaining: int | None = None
    exceeded: bool = False
    warning: bool = False  # True at >= 80% consumed


def check_token_budget(consumed: int, budget: int | None) -> TokenBudgetStatus:
    """Check token consumption against an optional budget."""
    if budget is None:
        return TokenBudgetStatus(consumed=consumed)
    if budget <= 0:
        return TokenBudgetStatus(
            budget=budget, consumed=consumed, remaining=0, exceeded=True, warning=False
        )
    remaining = max(0, budget - consumed)
    exceeded = consumed >= budget
    warning = not exceeded and (consumed / budget >= 0.8)
    return TokenBudgetStatus(
        budget=budget,
        consumed=consumed,
        remaining=remaining,
        exceeded=exceeded,
        warning=warning,
    )


# ---------------------------------------------------------------------------
# Shared guardrail helpers (used by both execute_run and execute_run_stream)
# ---------------------------------------------------------------------------


def _validate_input_or_fail(
    prompt: UserPrompt,
    role: RoleDefinition,
    run_id: str,
    *,
    audit_logger: AuditLogger | None = None,
    model_override: Model | str | None = None,
    trigger_type: str | None = None,
    trigger_metadata: dict[str, str] | None = None,
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
                )
            )
        return result
    return None


def _handle_run_error(result: RunResult, exc: Exception, partial_output: str = "") -> None:
    """Populate *result* fields for a caught run-time exception."""
    result.success = False
    if isinstance(exc, ModelHTTPError):
        result.error = f"Model API error: {exc}"
    elif isinstance(exc, UsageLimitExceeded):
        result.error = f"Usage limit exceeded: {exc}"
    else:
        result.error = f"{type(exc).__name__}: {exc}"
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


def _audit_result(
    result: RunResult,
    role: RoleDefinition,
    prompt: UserPrompt,
    *,
    audit_logger: AuditLogger | None,
    trigger_type: str | None = None,
    trigger_metadata: dict[str, str] | None = None,
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
        )
    )


# ---------------------------------------------------------------------------
# Shared run preparation (used by both execute_run and execute_run_stream)
# ---------------------------------------------------------------------------


def _prepare_run(
    role: RoleDefinition,
    prompt: UserPrompt,
    *,
    audit_logger: AuditLogger | None = None,
    message_history: list | None = None,
    model_override: Model | str | None = None,
    trigger_type: str | None = None,
    trigger_metadata: dict[str, str] | None = None,
    extra_toolsets: list | None = None,
    skip_input_validation: bool = False,
) -> tuple[str, UsageLimits, dict[str, Any], RunResult | None]:
    """Shared pre-flight for execute_run / execute_run_stream.

    Returns ``(run_id, usage_limits, run_kwargs, blocked)`` where *blocked*
    is a failed ``RunResult`` if content validation rejected the input, else ``None``.
    """
    run_id = generate_id()

    blocked: RunResult | None = None
    if not skip_input_validation:
        blocked = _validate_input_or_fail(
            prompt,
            role,
            run_id,
            audit_logger=audit_logger,
            model_override=model_override,
            trigger_type=trigger_type,
            trigger_metadata=trigger_metadata,
        )

    guardrails = role.spec.guardrails
    usage_limits = UsageLimits(
        output_tokens_limit=guardrails.max_tokens_per_run,
        request_limit=guardrails.max_request_limit,
        tool_calls_limit=guardrails.max_tool_calls,
        input_tokens_limit=guardrails.input_tokens_limit,
        total_tokens_limit=guardrails.total_tokens_limit,
    )

    run_kwargs: dict[str, Any] = {
        "usage_limits": usage_limits,
        "message_history": message_history,
        "model": model_override,
    }
    if extra_toolsets:
        run_kwargs["toolsets"] = extra_toolsets

    return run_id, usage_limits, run_kwargs, blocked


# ---------------------------------------------------------------------------
# Non-streaming execution
# ---------------------------------------------------------------------------


def execute_run(
    agent: Agent,
    role: RoleDefinition,
    prompt: UserPrompt,
    *,
    audit_logger: AuditLogger | None = None,
    message_history: list | None = None,
    model_override: Model | str | None = None,
    trigger_type: str | None = None,
    trigger_metadata: dict[str, str] | None = None,
    extra_toolsets: list | None = None,
    skip_input_validation: bool = False,
) -> tuple[RunResult, list]:
    """Execute a single agent run, returning the result and updated message history."""
    run_id, _usage_limits, run_kwargs, blocked = _prepare_run(
        role,
        prompt,
        audit_logger=audit_logger,
        message_history=message_history,
        model_override=model_override,
        trigger_type=trigger_type,
        trigger_metadata=trigger_metadata,
        extra_toolsets=extra_toolsets,
        skip_input_validation=skip_input_validation,
    )
    if blocked is not None:
        return blocked, []

    from opentelemetry import trace

    tracer = trace.get_tracer("initrunner")

    result = RunResult(run_id=run_id)
    new_messages: list = []
    start = time.monotonic()

    with tracer.start_as_current_span(
        "initrunner.agent.run",
        attributes={
            "initrunner.run_id": run_id,
            "initrunner.agent_name": role.metadata.name,
            "initrunner.trigger_type": trigger_type or "",
        },
    ) as span:
        try:
            agent_result = _run_with_timeout(
                lambda: _retry_model_call(lambda: agent.run_sync(prompt, **run_kwargs)),
                timeout=role.spec.guardrails.timeout_seconds,
            )

            raw_output = agent_result.output
            if isinstance(raw_output, (dict, list)):
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
        except (ModelHTTPError, UsageLimitExceeded, ConnectionError, TimeoutError, OSError) as e:
            _handle_run_error(result, e)

        result.duration_ms = int((time.monotonic() - start) * 1000)

        span.set_attribute("initrunner.tokens_total", result.total_tokens)
        span.set_attribute("initrunner.duration_ms", result.duration_ms)
        span.set_attribute("initrunner.success", result.success)

    _audit_result(
        result,
        role,
        prompt,
        audit_logger=audit_logger,
        trigger_type=trigger_type,
        trigger_metadata=trigger_metadata,
    )

    return result, new_messages


# ---------------------------------------------------------------------------
# Streaming execution (with same guardrails as execute_run)
# ---------------------------------------------------------------------------


def execute_run_stream(
    agent: Agent,
    role: RoleDefinition,
    prompt: UserPrompt,
    *,
    audit_logger: AuditLogger | None = None,
    message_history: list | None = None,
    model_override: Model | str | None = None,
    on_token: Callable[[str], None] | None = None,
    extra_toolsets: list | None = None,
    trigger_type: str | None = None,
    trigger_metadata: dict[str, str] | None = None,
    skip_input_validation: bool = False,
) -> tuple[RunResult, list]:
    """Execute a streaming agent run with guardrails, audit, and token callback.

    Applies the same pre-run content validation, usage limits, post-run output
    validation, and audit logging as ``execute_run``.
    """
    run_id, _usage_limits, stream_kwargs, blocked = _prepare_run(
        role,
        prompt,
        audit_logger=audit_logger,
        message_history=message_history,
        model_override=model_override,
        trigger_type=trigger_type,
        trigger_metadata=trigger_metadata,
        extra_toolsets=extra_toolsets,
        skip_input_validation=skip_input_validation,
    )
    if blocked is not None:
        return blocked, []

    from opentelemetry import trace

    tracer = trace.get_tracer("initrunner")

    result = RunResult(run_id=run_id)
    new_messages: list = []
    output_parts: list[str] = []
    start = time.monotonic()

    stream_state: dict = {"messages": [], "usage": None}

    with tracer.start_as_current_span(
        "initrunner.agent.run",
        attributes={
            "initrunner.run_id": run_id,
            "initrunner.agent_name": role.metadata.name,
            "initrunner.trigger_type": trigger_type or "",
        },
    ) as span:
        try:

            def _do_stream():
                stream = agent.run_stream_sync(
                    prompt,
                    **stream_kwargs,
                )
                for chunk in stream.stream_text(delta=True):
                    output_parts.append(chunk)
                    if on_token is not None:
                        on_token(chunk)

                stream_state["messages"] = stream.all_messages()
                stream_state["usage"] = stream.usage()

            _run_with_timeout(
                lambda: _retry_model_call(_do_stream, on_retry=output_parts.clear),
                timeout=role.spec.guardrails.timeout_seconds,
            )
            new_messages = stream_state["messages"]
            usage = stream_state["usage"]

            result.output = "".join(output_parts)

            _apply_output_validation(result, role)

            if usage is not None:
                result.tokens_in = usage.input_tokens or 0
                result.tokens_out = usage.output_tokens or 0
                result.total_tokens = usage.total_tokens or 0
        except (ModelHTTPError, UsageLimitExceeded, ConnectionError, TimeoutError, OSError) as e:
            _handle_run_error(result, e, partial_output="".join(output_parts))

        result.duration_ms = int((time.monotonic() - start) * 1000)

        span.set_attribute("initrunner.tokens_total", result.total_tokens)
        span.set_attribute("initrunner.duration_ms", result.duration_ms)
        span.set_attribute("initrunner.success", result.success)

    _audit_result(
        result,
        role,
        prompt,
        audit_logger=audit_logger,
        trigger_type=trigger_type,
        trigger_metadata=trigger_metadata,
    )

    return result, new_messages
