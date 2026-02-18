"""Guardrails configuration."""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, Field, model_validator


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

    # Autonomous mode limits
    max_iterations: Annotated[int, Field(gt=0)] = 10
    autonomous_token_budget: Annotated[int, Field(gt=0)] | None = None
    autonomous_timeout_seconds: Annotated[int, Field(gt=0)] | None = None

    @model_validator(mode="after")
    def _derive_request_limit(self) -> Guardrails:
        if self.max_request_limit is None:
            self.max_request_limit = max(self.max_tool_calls + 10, 30)
        return self
