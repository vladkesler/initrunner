"""Cross-cutting models used by multiple domain modules."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

__all__ = [
    "AgentSlotModel",
    "AgentSlotOption",
    "DeleteResponse",
    "ItemSummary",
    "ModelOption",
    "ProviderModels",
    "ProviderPreset",
    "ProviderStatus",
    "SkillRef",
    "TimelineCostResponse",
    "TimelineEntryResponse",
    "TimelineResponse",
    "TimelineStatsResponse",
    "ValidationIssueResponse",
]


class DeleteResponse(BaseModel):
    """Confirmation that an entity was deleted."""

    id: str
    path: str


class ItemSummary(BaseModel):
    """Flattened summary for tools, triggers, and sinks."""

    type: str
    summary: str
    config: dict = {}


class ValidationIssueResponse(BaseModel):
    field: str
    message: str
    severity: str  # "error" | "warning"


class SkillRef(BaseModel):
    """Resolved skill reference for agent detail cross-linking."""

    name: str
    skill_id: str | None = None


class ModelOption(BaseModel):
    name: str
    description: str


class ProviderModels(BaseModel):
    provider: str
    models: list[ModelOption]


class ProviderPreset(BaseModel):
    name: str
    label: str
    base_url: str
    api_key_env: str
    placeholder: str
    key_configured: bool = False


class ProviderStatus(BaseModel):
    provider: str
    env_var: str
    is_configured: bool


class AgentSlotModel(BaseModel):
    """Model metadata for an agent picker option."""

    provider: str
    name: str
    base_url: str | None = None
    api_key_env: str | None = None


class AgentSlotOption(BaseModel):
    id: str
    name: str
    description: str
    path: str
    tags: list[str] = []
    features: list[str] = []
    model: AgentSlotModel | None = None


class TimelineCostResponse(BaseModel):
    total_cost_usd: float


class TimelineEntryResponse(BaseModel):
    run_id: str
    start_time: str
    end_time: str
    duration_ms: int
    status: Literal["success", "error"]
    trigger_type: str | None = None
    trigger_metadata: dict | None = None
    tokens_in: int = 0
    tokens_out: int = 0
    total_tokens: int = 0
    tool_calls: int = 0
    cost: TimelineCostResponse | None = None


class TimelineStatsResponse(BaseModel):
    total_runs: int = 0
    success_count: int = 0
    error_count: int = 0
    success_rate: float = 0.0
    total_tokens: int = 0
    avg_duration_ms: int = 0
    max_duration_ms: int = 0
    total_cost_usd: float | None = None


class TimelineResponse(BaseModel):
    entries: list[TimelineEntryResponse]
    stats: TimelineStatsResponse
