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
    end_strategy: Literal["early", "graceful", "exhaustive"] = "graceful"
    tool_timeout_seconds: Annotated[float, Field(gt=0)] | None = None
    max_concurrency: ConcurrencyConfig | None = None
    http_retries: Annotated[int, Field(ge=1, le=10)] = 3
    """Total attempts per provider HTTP request for transient errors
    (429/5xx). Applied at the httpx transport layer with exponential backoff
    and ``Retry-After`` support."""
    http_retry_max_wait: Annotated[float, Field(gt=0, le=600)] = 60.0
    """Cap in seconds for a single retry wait (backoff or Retry-After)."""
