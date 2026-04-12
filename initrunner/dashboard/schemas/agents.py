"""Agent list, detail, and execution models."""

from __future__ import annotations

from pydantic import BaseModel

from initrunner.dashboard.schemas._common import ItemSummary, SkillRef

__all__ = [
    "AgentDetail",
    "AgentSummary",
    "RunRequest",
    "RunResponse",
]


class AgentSummary(BaseModel):
    id: str
    name: str
    description: str
    tags: list[str]
    provider: str
    model: str
    features: list[str]
    path: str
    error: str | None = None


class AgentDetail(BaseModel):
    """Full agent configuration for the detail page."""

    id: str
    name: str
    description: str
    tags: list[str]
    path: str
    error: str | None = None
    # metadata
    author: str = ""
    team: str = ""
    version: str = ""
    # existing config blocks (returned directly)
    model: dict  # ModelConfig serialised
    output: dict  # OutputConfig serialised
    guardrails: dict  # Guardrails serialised
    memory: dict | None = None  # MemoryConfig serialised
    ingest: dict | None = None  # IngestConfig serialised
    reasoning: dict | None = None  # ReasoningConfig serialised
    autonomy: dict | None = None  # AutonomyConfig serialised
    # flattened summaries (discriminated unions)
    tools: list[ItemSummary] = []
    triggers: list[ItemSummary] = []
    sinks: list[ItemSummary] = []
    capabilities: list[ItemSummary] = []
    # simple lists
    skills: list[str] = []
    skill_refs: list[SkillRef] = []
    features: list[str] = []
    tool_search: dict | None = None  # ToolSearchConfig serialised (when enabled)
    # runtime readiness
    provider_warning: str | None = None


class RunRequest(BaseModel):
    agent_id: str
    prompt: str
    model_override: str | None = None
    message_history: str | None = None


class RunResponse(BaseModel):
    run_id: str
    output: str
    tokens_in: int
    tokens_out: int
    total_tokens: int
    tool_calls: int
    tool_call_names: list[str]
    duration_ms: int
    success: bool
    error: str | None = None
    message_history: str | None = None
