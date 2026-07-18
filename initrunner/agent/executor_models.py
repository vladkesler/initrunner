"""Result dataclasses and token budget helpers for agent execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Literal

RunStatus = Literal["done", "paused"]


@dataclass
class PendingApproval:
    """A tool call the agent wants to execute, awaiting human approval."""

    tool_call_id: str
    tool_name: str
    arguments: dict[str, Any]


class ErrorCategory(StrEnum):
    """Structured error classification for retry and circuit breaker decisions."""

    TIMEOUT = "timeout"
    RATE_LIMIT = "rate_limit"
    SERVER_ERROR = "server_error"
    AUTH = "auth"
    CONNECTION = "connection"
    USAGE_LIMIT = "usage_limit"
    CONTENT_BLOCKED = "content_blocked"
    UNKNOWN = "unknown"


@dataclass
class RunResult:
    run_id: str
    output: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    total_tokens: int = 0
    thinking_tokens: int = 0
    reasoning_tokens: int = 0
    """Reasoning/thinking tokens reported in the final streaming event. Mirrors
    ``thinking_tokens`` for the non-streaming path; the streaming consumer may
    override it from ``AgentRunResultEvent.result.usage``."""
    cache_hit_ratio: float | None = None
    """Fraction of input tokens served from the provider prompt cache, reported
    by PydanticAI's run usage (``0.0`` to ``1.0``). ``None`` when the model or
    provider does not report cache usage (e.g. ``TestModel`` or a non-caching
    provider); only meaningful for the Anthropic/Bedrock prompt-caching path."""
    tool_calls: int = 0
    duration_ms: int = 0
    success: bool = True
    error: str | None = None
    error_category: ErrorCategory | None = None
    tool_call_names: list[str] = field(default_factory=list)
    event_timeline: list[dict[str, Any]] = field(default_factory=list)
    """Redacted, best-effort log of streaming thinking/tool deltas captured from
    ``run_stream_events()``. Empty for non-streaming runs and for streaming runs
    without an ``on_event`` consumer. Capped at the most recent entries; every
    free-text value is secret-scrubbed before it lands here."""
    status: RunStatus = "done"
    """``"paused"`` when the run surfaced ``DeferredToolRequests`` awaiting
    human approval; ``"done"`` otherwise. Paused runs have ``success=True``
    and produce no ``output`` — the caller must resolve every entry in
    ``pending_approvals`` and then call ``execute_run_resume()``.
    """
    pending_approvals: list[PendingApproval] = field(default_factory=list)
    judge_verdicts: list[dict[str, Any]] = field(default_factory=list)
    """Verified-reflexion judge verdicts copied from the autonomous
    ``ReflectionState`` onto the final iteration result, so the audit layer can
    persist them. Empty for non-reflexion runs and runs without success
    criteria. Each entry mirrors ``ReflectionState.judge_verdicts``."""


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
    error_category: ErrorCategory | None = None
    final_messages: list | None = None


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
