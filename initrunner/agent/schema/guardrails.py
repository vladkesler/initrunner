"""Guardrails configuration."""

from __future__ import annotations

from typing import Annotated
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field, field_validator, model_validator


class RetryPolicy(BaseModel):
    """Daemon-level retry policy for failed runs."""

    max_attempts: Annotated[int, Field(ge=1, le=5)] = 1
    backoff_base_seconds: Annotated[float, Field(ge=0.5, le=30.0)] = 2.0
    backoff_max_seconds: Annotated[float, Field(ge=1.0, le=300.0)] = 30.0


class CircuitBreakerConfig(BaseModel):
    """Per-daemon circuit breaker to stop wasting triggers against a broken provider."""

    failure_threshold: Annotated[int, Field(ge=1, le=100)] = 5
    reset_timeout_seconds: Annotated[int, Field(ge=10, le=3600)] = 60


class Guardrails(BaseModel):
    max_tokens_per_run: Annotated[int, Field(gt=0)] = 50000
    max_tool_calls: Annotated[int, Field(ge=0)] = 20
    timeout_seconds: Annotated[int, Field(gt=0)] = 300
    max_request_limit: Annotated[int, Field(gt=0)] | None = None

    # Per-run limits (mapped to PydanticAI UsageLimits)
    input_tokens_limit: Annotated[int, Field(gt=0)] | None = None
    total_tokens_limit: Annotated[int, Field(gt=0)] | None = None

    # Cumulative budgets
    session_token_budget: Annotated[int, Field(gt=0)] | None = None
    daemon_token_budget: Annotated[int, Field(gt=0)] | None = None
    daemon_daily_token_budget: Annotated[int, Field(gt=0)] | None = None

    # Cumulative cost budgets (USD)
    daemon_daily_cost_budget: Annotated[float, Field(gt=0)] | None = None
    daemon_weekly_cost_budget: Annotated[float, Field(gt=0)] | None = None

    # Timezone for daily/weekly budget resets (IANA, e.g. "America/New_York")
    budget_timezone: str = "UTC"

    # Autonomous mode limits
    max_iterations: Annotated[int, Field(gt=0)] = 10
    autonomous_token_budget: Annotated[int, Field(gt=0)] | None = None
    autonomous_timeout_seconds: Annotated[int, Field(gt=0)] | None = None

    # Daemon resilience
    retry_policy: RetryPolicy = RetryPolicy()
    circuit_breaker: CircuitBreakerConfig | None = None

    @field_validator("budget_timezone")
    @classmethod
    def _validate_budget_timezone(cls, v: str) -> str:
        try:
            ZoneInfo(v)
        except (KeyError, ZoneInfoNotFoundError) as exc:
            raise ValueError(f"Invalid IANA timezone: {v!r}") from exc
        return v

    @model_validator(mode="after")
    def _derive_request_limit(self) -> Guardrails:
        if self.max_request_limit is None:
            self.max_request_limit = max(self.max_tool_calls + 10, 30)
        return self
