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
from pydantic_ai.models.fallback import FallbackExceptionGroup

from initrunner._async import run_sync
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
    _finalize_run_output,
    _handle_run_error,
    _process_agent_output,
    _record_span_metrics,
    _validate_input_or_fail,
)
from .executor_retry import (
    _retry_model_call,  # noqa: F401
    _retry_model_call_async,
    _run_with_timeout,  # noqa: F401
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
    metadata: dict[str, Any] = {
        "initrunner.run_id": run_id,
        "initrunner.agent_name": role.metadata.name,
    }
    if trigger_type:
        metadata["initrunner.trigger_type"] = trigger_type
    # Tell InputGuardCapability to skip validation when the caller already
    # checked (e.g. the API server pre-flight) or when pre-flight passed.
    if skip_input_validation or blocked is None:
        metadata["input_validated"] = True
    run_kwargs["metadata"] = metadata

    return run_id, usage_limits, run_kwargs, blocked


# ---------------------------------------------------------------------------
# Shared async orchestration skeleton
# ---------------------------------------------------------------------------


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
    judge_verdicts: list[dict[str, Any]] | None = None,
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
                FallbackExceptionGroup,
            ) as e:
                on_error(result, e)

            result.duration_ms = int((time.monotonic() - start) * 1000)
            _record_span_metrics(span, result)

        if judge_verdicts:
            result.judge_verdicts = list(judge_verdicts)

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
    judge_verdicts: list[dict[str, Any]] | None = None,
) -> tuple[RunResult, list]:
    """Sync wrapper around ``execute_run_async`` (owns the event loop)."""
    return run_sync(
        execute_run_async(
            agent,
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
            judge_verdicts=judge_verdicts,
        )
    )


# ---------------------------------------------------------------------------
# Resume execution (human-in-the-loop approval)
# ---------------------------------------------------------------------------


def _resume_prompt(approvals: dict[str, bool]) -> UserPrompt:
    """Synthetic prompt recorded in the audit trail for a resume."""
    decisions = ", ".join(f"{tcid}:{'approve' if ok else 'deny'}" for tcid, ok in approvals.items())
    return f"(resume: {decisions})"


async def _execute_resume_async_inner(
    agent: Agent,
    role: RoleDefinition,
    *,
    run_id: str,
    message_history: list,
    approvals: dict[str, bool],
    audit_logger: AuditLogger | None = None,
    model_override: Model | str | None = None,
    principal_id: str | None = None,
) -> tuple[RunResult, list]:
    """Shared async body for ``execute_run_resume`` and ``execute_run_resume_async``."""
    from pydantic_ai import DeferredToolResults

    agent_token = _enter_agent_context(role)
    try:
        result = RunResult(run_id=run_id)
        start = time.monotonic()
        deferred = DeferredToolResults(approvals=dict(approvals))
        run_kwargs: dict[str, Any] = {
            "message_history": message_history,
            "deferred_tool_results": deferred,
            "model": model_override,
            "metadata": {"input_validated": True},
        }
        new_messages: list = []
        timeout = role.spec.guardrails.timeout_seconds

        with _create_run_span(run_id, role, trigger_type="resume") as span:
            try:
                agent_result = await asyncio.wait_for(
                    _retry_model_call_async(lambda: agent.run(**run_kwargs)),
                    timeout=timeout,
                )
                new_messages = _process_agent_output(
                    agent_result, result, role, capture_timeline=audit_logger is not None
                )
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
                FallbackExceptionGroup,
            ) as e:
                _handle_run_error(result, e, timeout_seconds=timeout)

            result.duration_ms = int((time.monotonic() - start) * 1000)
            _record_span_metrics(span, result)

        _audit_result(
            result,
            role,
            _resume_prompt(approvals),
            audit_logger=audit_logger,
            trigger_type="resume",
            principal_id=principal_id,
        )
        return result, new_messages
    finally:
        _exit_agent_context(agent_token)


def execute_run_resume(
    agent: Agent,
    role: RoleDefinition,
    *,
    run_id: str,
    message_history: list,
    approvals: dict[str, bool],
    audit_logger: AuditLogger | None = None,
    model_override: Model | str | None = None,
    principal_id: str | None = None,
) -> tuple[RunResult, list]:
    """Resume a paused run by supplying approvals for pending tool calls.

    Unlike ``execute_run`` this does not take a new prompt — the model
    already produced one, the user just answered the approval question.
    On re-pause (the model queues more approval-required calls after
    executing the approved ones) the returned ``RunResult`` has
    ``status="paused"`` again with a fresh ``pending_approvals`` list.
    """
    return run_sync(
        _execute_resume_async_inner(
            agent,
            role,
            run_id=run_id,
            message_history=message_history,
            approvals=approvals,
            audit_logger=audit_logger,
            model_override=model_override,
            principal_id=principal_id,
        )
    )


async def execute_run_resume_async(
    agent: Agent,
    role: RoleDefinition,
    *,
    run_id: str,
    message_history: list,
    approvals: dict[str, bool],
    audit_logger: AuditLogger | None = None,
    model_override: Model | str | None = None,
    principal_id: str | None = None,
) -> tuple[RunResult, list]:
    """Async variant of ``execute_run_resume``."""
    return await _execute_resume_async_inner(
        agent,
        role,
        run_id=run_id,
        message_history=message_history,
        approvals=approvals,
        audit_logger=audit_logger,
        model_override=model_override,
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
    on_partial: Callable[[Any], None] | None = None,
    extra_toolsets: list | None = None,
    trigger_type: str | None = None,
    trigger_metadata: dict[str, str] | None = None,
    skip_input_validation: bool = False,
    principal_id: str | None = None,
) -> tuple[RunResult, list]:
    """Sync wrapper around ``execute_run_stream_async`` (owns the event loop)."""
    return run_sync(
        execute_run_stream_async(
            agent,
            role,
            prompt,
            audit_logger=audit_logger,
            message_history=message_history,
            model_override=model_override,
            on_token=on_token,
            on_partial=on_partial,
            extra_toolsets=extra_toolsets,
            trigger_type=trigger_type,
            trigger_metadata=trigger_metadata,
            skip_input_validation=skip_input_validation,
            principal_id=principal_id,
        )
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
    judge_verdicts: list[dict[str, Any]] | None = None,
) -> tuple[RunResult, list]:
    """Async variant of ``execute_run`` -- uses ``agent.run()`` + ``asyncio.wait_for``."""
    timeout = role.spec.guardrails.timeout_seconds
    # When the run will be audited, reconstruct the tool-call/result timeline
    # from the run's messages -- the buffered path has no live stream events.
    capture_timeline = audit_logger is not None

    async def invoke(run_kwargs: dict, result: RunResult) -> list:
        agent_result = await asyncio.wait_for(
            _retry_model_call_async(lambda: agent.run(prompt, **run_kwargs)),
            timeout=timeout,
        )
        return _process_agent_output(agent_result, result, role, capture_timeline=capture_timeline)

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
        judge_verdicts=judge_verdicts,
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
    on_partial: Callable[[Any], None] | None = None,
    on_event: Callable[[Any], None] | None = None,
    extra_toolsets: list | None = None,
    trigger_type: str | None = None,
    trigger_metadata: dict[str, str] | None = None,
    skip_input_validation: bool = False,
    principal_id: str | None = None,
) -> tuple[RunResult, list]:
    """Async variant of ``execute_run_stream``.

    Two backbones based on ``on_event``:

    - ``on_event`` set: uses ``agent.run_stream_events()`` to yield typed
      ``AgentStreamEvent`` instances. Text deltas still route to ``on_token``
      when extractable from ``PartDeltaEvent``. Final result comes from
      ``AgentRunResultEvent.result``.
    - ``on_event`` unset: uses ``async with agent.run_stream(...) as stream``,
      iterates ``stream_text(delta=True)`` (text roles) or ``stream_output()``
      (structured roles), and finalizes via ``stream.get_output()``.

    Both backbones finalize through ``_finalize_run_output`` so deferred
    approvals, BaseModel serialization, and output validation behave
    identically to non-streaming runs.
    """
    timeout = role.spec.guardrails.timeout_seconds
    is_structured = role.spec.output.type != "text"
    output_parts: list[str] = []
    event_timeline: list[dict[str, Any]] = []
    # When the run will be audited, persist the timeline even without a live
    # on_event consumer. The on_event backbone builds it from live stream
    # events; the run_stream backbone reconstructs it from the final messages.
    capture_timeline = audit_logger is not None

    async def invoke(run_kwargs: dict, result: RunResult) -> list:
        stream_state: dict[str, Any] = {
            "messages": [],
            "usage": None,
            "output": None,
            "reasoning_tokens": None,
        }

        if on_event is not None:

            async def _do_stream_events():
                from pydantic_ai import AgentRunResultEvent
                from pydantic_ai.messages import PartDeltaEvent, TextPartDelta

                from .executor_output import (
                    _extract_reasoning_tokens,
                    build_timeline_entry,
                )

                # A retry replays the whole stream, so drop anything captured
                # by the prior attempt to keep the timeline consistent.
                event_timeline.clear()
                async for event in agent.run_stream_events(prompt, **run_kwargs):
                    on_event(event)
                    if isinstance(event, PartDeltaEvent) and isinstance(event.delta, TextPartDelta):
                        text = event.delta.content_delta
                        if text:
                            output_parts.append(text)
                            if on_token is not None:
                                on_token(text)
                        continue
                    if isinstance(event, AgentRunResultEvent):
                        stream_state["output"] = event.result.output
                        stream_state["usage"] = event.result.usage
                        stream_state["messages"] = event.result.all_messages()
                        stream_state["reasoning_tokens"] = _extract_reasoning_tokens(
                            event.result.usage
                        )
                        continue
                    entry = build_timeline_entry(event)
                    if entry is not None:
                        event_timeline.append(entry)

            await asyncio.wait_for(
                _retry_model_call_async(_do_stream_events, on_retry=output_parts.clear),
                timeout=timeout,
            )
        else:

            async def _do_stream():
                async with agent.run_stream(prompt, **run_kwargs) as stream:
                    if is_structured:
                        async for partial in stream.stream_output(debounce_by=0.05):
                            if on_partial is not None:
                                on_partial(partial)
                    else:
                        async for chunk in stream.stream_text(delta=True):
                            output_parts.append(chunk)
                            if on_token is not None:
                                on_token(chunk)
                    stream_state["messages"] = stream.all_messages()
                    stream_state["usage"] = stream.usage
                    stream_state["output"] = await stream.get_output()

            await asyncio.wait_for(
                _retry_model_call_async(_do_stream, on_retry=output_parts.clear),
                timeout=timeout,
            )

        _finalize_run_output(
            stream_state["output"],
            stream_state["usage"],
            stream_state["messages"],
            result,
            role,
            reasoning_tokens=stream_state["reasoning_tokens"],
            event_timeline=event_timeline if on_event is not None else None,
            capture_timeline=capture_timeline,
        )
        return stream_state["messages"]

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
