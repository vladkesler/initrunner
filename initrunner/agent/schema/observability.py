"""OpenTelemetry observability configuration."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ObservabilityConfig(BaseModel):
    """OpenTelemetry observability configuration."""

    backend: Literal["otlp", "logfire", "console"] = "otlp"
    endpoint: str = "http://localhost:4317"
    service_name: str = ""  # empty = use agent metadata.name
    trace_tool_calls: bool = True
    trace_token_usage: bool = True
    sample_rate: float = Field(default=1.0, ge=0.0, le=1.0)
    include_content: bool = False
