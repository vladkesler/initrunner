"""Flow list, detail, execution, and builder models."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from initrunner.dashboard.schemas._common import (
    AgentSlotOption,
    ProviderModels,
    ProviderPreset,
    ValidationIssueResponse,
)

__all__ = [
    "AgentStepResponse",
    "DelegateEventResponse",
    "FlowAgentDetail",
    "FlowBuilderOptionsResponse",
    "FlowDetail",
    "FlowRunRequest",
    "FlowRunResponse",
    "FlowSaveRequest",
    "FlowSaveResponse",
    "FlowSeedRequest",
    "FlowSeedResponse",
    "FlowStatsResponse",
    "FlowSummary",
    "FlowValidateRequest",
    "FlowValidateResponse",
    "FlowYamlSaveRequest",
    "FlowYamlSaveResponse",
    "HealthCheckDetail",
    "PatternInfo",
    "RestartDetail",
    "SinkDetail",
    "SlotAssignment",
]


class FlowSummary(BaseModel):
    id: str
    name: str
    description: str
    agent_count: int
    agent_names: list[str]
    path: str
    error: str | None = None


class SinkDetail(BaseModel):
    summary: str
    strategy: str
    targets: list[str] = Field(default_factory=list)
    queue_size: int = 100
    timeout_seconds: int = 60
    circuit_breaker_threshold: int | None = None


class RestartDetail(BaseModel):
    condition: str = "none"
    max_retries: int = 3
    delay_seconds: int = 5


class HealthCheckDetail(BaseModel):
    interval_seconds: int = 30
    timeout_seconds: int = 10
    retries: int = 3


class FlowAgentDetail(BaseModel):
    name: str
    role_path: str
    agent_id: str | None = None
    agent_name: str | None = None
    sink: SinkDetail | None = None
    needs: list[str] = Field(default_factory=list)
    trigger_summary: str | None = None
    restart: RestartDetail = Field(default_factory=RestartDetail)
    health_check: HealthCheckDetail = Field(default_factory=HealthCheckDetail)
    environment_count: int = 0


class FlowDetail(BaseModel):
    id: str
    name: str
    description: str
    path: str
    agents: list[FlowAgentDetail]
    shared_memory_enabled: bool = False
    shared_documents_enabled: bool = False


class DelegateEventResponse(BaseModel):
    timestamp: str
    source_agent: str
    target_agent: str
    status: str
    source_run_id: str
    flow_name: str | None = None
    reason: str | None = None
    trace: str | None = None
    payload_preview: str = ""


class FlowStatsResponse(BaseModel):
    total_events: int
    by_status: dict[str, int] = Field(default_factory=dict)


class FlowRunRequest(BaseModel):
    prompt: str
    message_history: str | None = None


class AgentStepResponse(BaseModel):
    agent_name: str
    output: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    duration_ms: int = 0
    tool_calls: int = 0
    tool_call_names: list[str] = Field(default_factory=list)
    success: bool = True
    error: str | None = None


class FlowRunResponse(BaseModel):
    output: str = ""
    output_mode: str = "none"
    final_agent_name: str | None = None
    steps: list[AgentStepResponse] = Field(default_factory=list)
    tokens_in: int = 0
    tokens_out: int = 0
    total_tokens: int = 0
    duration_ms: int = 0
    success: bool = True
    error: str | None = None
    message_history: str | None = None


class FlowYamlSaveRequest(BaseModel):
    yaml_text: str


class FlowYamlSaveResponse(BaseModel):
    path: str
    valid: bool
    issues: list[str] = Field(default_factory=list)


# -- Flow: builder -------------------------------------------------------------


class PatternInfo(BaseModel):
    name: str
    description: str
    fixed_topology: bool
    slot_names: list[str]
    min_agents: int
    max_agents: int | None = None


class SlotAssignment(BaseModel):
    slot: str
    agent_id: str | None = None


class FlowBuilderOptionsResponse(BaseModel):
    patterns: list[PatternInfo]
    agents: list[AgentSlotOption]
    providers: list[ProviderModels]
    detected_provider: str | None = None
    detected_model: str | None = None
    save_dirs: list[str]
    custom_presets: list[ProviderPreset]
    ollama_models: list[str]
    ollama_base_url: str


class FlowSeedRequest(BaseModel):
    mode: Literal["pattern", "starter"] = "pattern"
    pattern: str = ""
    name: str
    agents: list[SlotAssignment] = []
    agent_count: int = 3
    shared_memory: bool = False
    provider: str = "openai"
    model: str | None = None
    base_url: str | None = None
    api_key_env: str | None = None
    routing_strategy: Literal["all", "keyword", "sense"] | None = None
    starter_slug: str | None = None


class FlowSeedResponse(BaseModel):
    flow_yaml: str
    role_yamls: dict[str, str]
    issues: list[ValidationIssueResponse]
    ready: bool


class FlowValidateRequest(BaseModel):
    yaml_text: str


class FlowValidateResponse(BaseModel):
    issues: list[ValidationIssueResponse]
    ready: bool


class FlowSaveRequest(BaseModel):
    flow_yaml: str
    role_yamls: dict[str, str]
    directory: str
    project_name: str
    force: bool = False


class FlowSaveResponse(BaseModel):
    path: str
    valid: bool
    issues: list[str]
    next_steps: list[str]
    flow_id: str
