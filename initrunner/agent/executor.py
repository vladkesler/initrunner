"""Execute agent runs with guardrails and audit logging.

This module is the orchestration layer and compatibility facade. The
implementation is split across focused sub-modules:

- ``executor_models``  -- RunResult, AutonomousResult, TokenBudgetStatus
- ``executor_auth``    -- agent principal scoping, policy engine globals
- ``executor_retry``   -- retry + timeout resilience primitives
- ``executor_output``  -- validation, output processing, audit, observability

All names that were historically importable from this module are explicitly
re-imported below so that existing ``from initrunner.agent.executor import X``
statements continue to work.  The one exception is mutable globals
(``_cached_config``, ``_cached_engine``, ``_authz_resolved``) which live
exclusively in ``executor_auth``.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from typing import Any

from pydantic_ai import Agent, UsageLimits
from pydantic_ai.exceptions import ModelHTTPError, UsageLimitExceeded
from pydantic_ai.models import Model

from initrunner._ids import generate_id
from initrunner.agent.capabilities.content_guard import ContentBlockedError
from initrunner.agent.prompt import UserPrompt
from initrunner.agent.schema.role import RoleDefinition
from initrunner.audit.logger import AuditLogger

# ---------------------------------------------------------------------------
# Explicit re-exports from sub-modules (compatibility facade)
# ---------------------------------------------------------------------------
from .executor_auth import (
    _enter_agent_context,
    _exit_agent_context,
)
from .executor_models import (  # noqa: F401
    AutonomousResult,
    ErrorCategory,
    RunResult,
    TokenBudgetStatus,
    check_token_budget,
)
from .executor_output import (
    _audit_result,
    _create_run_span,
    _handle_run_error,
    _process_agent_output,
    _process_stream_output,
    _record_span_metrics,
    _validate_input_or_fail,
)
from .executor_retry import (
    _retry_model_call,
    _retry_model_call_async,
    _run_with_timeout,
    _should_retry,  # noqa: F401
)

# ---------------------------------------------------------------------------
# Shared run preparation
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
    principal_id: str | None = None,
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
            principal_id=principal_id,
        )

    guardrails = role.spec.guardrails

    # Builtin capabilities (WebSearch, WebFetch, etc.) register model-native
    # tools that PydanticAI counts against tool_calls_limit.  Disable that
    # guardrail when builtins are active so they don't starve actual tools.
    _BUILTIN_CAP_NAMES = {"WebSearch", "WebFetch", "ImageGeneration", "MCP"}
    has_builtins = any(
        hasattr(s, "name") and s.name in _BUILTIN_CAP_NAMES for s in role.spec.capabilities
    )
    tool_calls_limit = guardrails.max_tool_calls + 20 if has_builtins else guardrails.max_tool_calls

    usage_limits = UsageLimits(
        output_tokens_limit=guardrails.max_tokens_per_run,
        request_limit=guardrails.max_request_limit,
        tool_calls_limit=tool_calls_limit,
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
    # Tell InputGuardCapability to skip validation when the caller already
    # checked (e.g. the API server pre-flight) or when pre-flight passed.
    if skip_input_validation or blocked is None:
        run_kwargs["metadata"] = {"input_validated": True}

    return run_id, usage_limits, run_kwargs, blocked


# ---------------------------------------------------------------------------
# Shared orchestration skeletons
# ---------------------------------------------------------------------------


def _execute_orchestrated(
    invoke_fn: Callable[[dict, RunResult], list],
    on_error: Callable[[RunResult, Exception], None],
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
    principal_id: str | None = None,
) -> tuple[RunResult, list]:
    """Sync execution skeleton shared by ``execute_run`` and ``execute_run_stream``.

    *invoke_fn(run_kwargs, result) -> new_messages* performs the variant-specific
    agent call and output processing.  *on_error(result, exc)* handles recoverable
    errors (may set ``partial_output`` etc.).
    """
    agent_token = _enter_agent_context(role)
    try:
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
            principal_id=principal_id,
        )
        if blocked is not None:
            return blocked, []

        result = RunResult(run_id=run_id)
        new_messages: list = []
        start = time.monotonic()

        with _create_run_span(run_id, role, trigger_type) as span:
            try:
                new_messages = invoke_fn(run_kwargs, result)
            except ContentBlockedError as e:
                result.success = False
                result.error = e.reason
                result.error_category = ErrorCategory.CONTENT_BLOCKED
            except (
                ModelHTTPError,
                UsageLimitExceeded,
                ConnectionError,
                TimeoutError,
                OSError,
            ) as e:
                on_error(result, e)

            result.duration_ms = int((time.monotonic() - start) * 1000)
            _record_span_metrics(span, result)

        _audit_result(
            result,
            role,
            prompt,
            audit_logger=audit_logger,
            trigger_type=trigger_type,
            trigger_metadata=trigger_metadata,
            principal_id=principal_id,
        )

        return result, new_messages
    finally:
        _exit_agent_context(agent_token)


async def _execute_orchestrated_async(
    invoke_fn: Callable[[dict, RunResult], Any],
    on_error: Callable[[RunResult, Exception], None],
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
    principal_id: str | None = None,
) -> tuple[RunResult, list]:
    """Async execution skeleton shared by ``execute_run_async`` and ``execute_run_stream_async``."""
    agent_token = _enter_agent_context(role)
    try:
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
            principal_id=principal_id,
        )
        if blocked is not None:
            return blocked, []

        result = RunResult(run_id=run_id)
        new_messages: list = []
        start = time.monotonic()

        with _create_run_span(run_id, role, trigger_type) as span:
            try:
                new_messages = await invoke_fn(run_kwargs, result)
            except ContentBlockedError as e:
                result.success = False
                result.error = e.reason
                result.error_category = ErrorCategory.CONTENT_BLOCKED
            except (
                ModelHTTPError,
                UsageLimitExceeded,
                ConnectionError,
                TimeoutError,
                OSError,
            ) as e:
                on_error(result, e)

            result.duration_ms = int((time.monotonic() - start) * 1000)
            _record_span_metrics(span, result)

        _audit_result(
            result,
            role,
            prompt,
            audit_logger=audit_logger,
            trigger_type=trigger_type,
            trigger_metadata=trigger_metadata,
            principal_id=principal_id,
        )

        return result, new_messages
    finally:
        _exit_agent_context(agent_token)


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
    principal_id: str | None = None,
) -> tuple[RunResult, list]:
    """Execute a single agent run, returning the result and updated message history."""

    def invoke(run_kwargs: dict, result: RunResult) -> list:
        agent_result = _run_with_timeout(
            lambda: _retry_model_call(lambda: agent.run_sync(prompt, **run_kwargs)),
            timeout=role.spec.guardrails.timeout_seconds,
        )
        return _process_agent_output(agent_result, result, role)

    return _execute_orchestrated(
        invoke,
        _handle_run_error,
        role,
        prompt,
        audit_logger=audit_logger,
        message_history=message_history,
        model_override=model_override,
        trigger_type=trigger_type,
        trigger_metadata=trigger_metadata,
        extra_toolsets=extra_toolsets,
        skip_input_validation=skip_input_validation,
        principal_id=principal_id,
    )


# ---------------------------------------------------------------------------
# Streaming execution
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
    principal_id: str | None = None,
) -> tuple[RunResult, list]:
    """Execute a streaming agent run with guardrails, audit, and token callback."""
    if role.spec.output.type != "text":
        raise ValueError(
            "Streaming is not supported with structured output "
            f"(output.type={role.spec.output.type!r}). "
            "Use non-streaming execution instead."
        )

    output_parts: list[str] = []

    def invoke(run_kwargs: dict, result: RunResult) -> list:
        stream_state: dict = {"messages": [], "usage": None}

        def _do_stream():
            stream = agent.run_stream_sync(prompt, **run_kwargs)
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
        _process_stream_output(output_parts, stream_state["usage"], new_messages, result, role)
        return new_messages

    return _execute_orchestrated(
        invoke,
        lambda r, e: _handle_run_error(r, e, partial_output="".join(output_parts)),
        role,
        prompt,
        audit_logger=audit_logger,
        message_history=message_history,
        model_override=model_override,
        trigger_type=trigger_type,
        trigger_metadata=trigger_metadata,
        extra_toolsets=extra_toolsets,
        skip_input_validation=skip_input_validation,
        principal_id=principal_id,
    )


# ---------------------------------------------------------------------------
# Async non-streaming execution
# ---------------------------------------------------------------------------


async def execute_run_async(
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
    principal_id: str | None = None,
) -> tuple[RunResult, list]:
    """Async variant of ``execute_run`` -- uses ``agent.run()`` + ``asyncio.wait_for``."""
    timeout = role.spec.guardrails.timeout_seconds

    async def invoke(run_kwargs: dict, result: RunResult) -> list:
        agent_result = await asyncio.wait_for(
            _retry_model_call_async(lambda: agent.run(prompt, **run_kwargs)),
            timeout=timeout,
        )
        return _process_agent_output(agent_result, result, role)

    return await _execute_orchestrated_async(
        invoke,
        lambda r, e: _handle_run_error(r, e, timeout_seconds=timeout),
        role,
        prompt,
        audit_logger=audit_logger,
        message_history=message_history,
        model_override=model_override,
        trigger_type=trigger_type,
        trigger_metadata=trigger_metadata,
        extra_toolsets=extra_toolsets,
        skip_input_validation=skip_input_validation,
        principal_id=principal_id,
    )


# ---------------------------------------------------------------------------
# Async streaming execution
# ---------------------------------------------------------------------------


async def execute_run_stream_async(
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
    principal_id: str | None = None,
) -> tuple[RunResult, list]:
    """Async variant of ``execute_run_stream`` -- uses ``agent.run_stream()``."""
    if role.spec.output.type != "text":
        raise ValueError(
            "Streaming is not supported with structured output "
            f"(output.type={role.spec.output.type!r}). "
            "Use non-streaming execution instead."
        )

    timeout = role.spec.guardrails.timeout_seconds
    output_parts: list[str] = []
    new_messages_ref: list = []

    async def invoke(run_kwargs: dict, result: RunResult) -> list:
        nonlocal new_messages_ref

        async def _do_stream():
            async with agent.run_stream(prompt, **run_kwargs) as stream:
                async for chunk in stream.stream_text(delta=True):
                    output_parts.append(chunk)
                    if on_token is not None:
                        on_token(chunk)

                nonlocal new_messages_ref
                new_messages_ref = stream.all_messages()
                return stream.usage()

        usage = await asyncio.wait_for(
            _retry_model_call_async(_do_stream, on_retry=output_parts.clear),
            timeout=timeout,
        )
        _process_stream_output(output_parts, usage, new_messages_ref, result, role)
        return new_messages_ref

    return await _execute_orchestrated_async(
        invoke,
        lambda r, e: _handle_run_error(
            r, e, partial_output="".join(output_parts), timeout_seconds=timeout
        ),
        role,
        prompt,
        audit_logger=audit_logger,
        message_history=message_history,
        model_override=model_override,
        trigger_type=trigger_type,
        trigger_metadata=trigger_metadata,
        extra_toolsets=extra_toolsets,
        skip_input_validation=skip_input_validation,
        principal_id=principal_id,
    )
