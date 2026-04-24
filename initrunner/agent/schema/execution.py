"""Agent execution-semantics config.

Thin wrapper over PydanticAI's agent-level execution knobs (``retries``,
``output_retries``, ``end_strategy``, ``tool_timeout``). Kept separate from
``Guardrails`` -- budgets and rate limits live there; per-run and per-tool
retry/termination semantics live here.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field


class ConcurrencyConfig(BaseModel):
    max_running: Annotated[int, Field(ge=1)]
    max_queued: Annotated[int, Field(ge=0)] | None = None


class ExecutionConfig(BaseModel):
    retries: Annotated[int, Field(ge=0, le=10)] = 1
    output_retries: Annotated[int, Field(ge=0, le=10)] | None = None
    end_strategy: Literal["early", "exhaustive"] = "early"
    tool_timeout_seconds: Annotated[float, Field(gt=0)] | None = None
    max_concurrency: ConcurrencyConfig | None = None
