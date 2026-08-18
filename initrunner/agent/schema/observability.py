"""OpenTelemetry observability configuration."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ObservabilityConfig(BaseModel):
    """OpenTelemetry observability configuration."""

    model_config = ConfigDict(extra="forbid")

    backend: Literal["otlp", "logfire", "console"] = "otlp"
    endpoint: str = "http://localhost:4317"
    service_name: str = ""  # empty = use the agent name
    trace_tool_calls: bool = True
    trace_token_usage: bool = True
    sample_rate: float = Field(default=1.0, ge=0.0, le=1.0)
    include_content: bool = False
