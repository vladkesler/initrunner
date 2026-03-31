"""Result dataclasses and token budget helpers for agent execution."""

from __future__ import annotations

from dataclasses import dataclass, field


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
    tool_call_names: list[str] = field(default_factory=list)


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
