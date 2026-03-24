"""Pydantic response/request models for the dashboard API."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


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


class ItemSummary(BaseModel):
    """Flattened summary for tools, triggers, and sinks."""

    type: str
    summary: str


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
    # simple lists
    skills: list[str] = []
    features: list[str] = []


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


class AuditRecordResponse(BaseModel):
    run_id: str
    agent_name: str
    timestamp: str
    user_prompt: str
    model: str
    provider: str
    output: str
    tokens_in: int
    tokens_out: int
    total_tokens: int
    tool_calls: int
    duration_ms: int
    success: bool
    error: str | None = None
    trigger_type: str | None = None


class ProviderResponse(BaseModel):
    provider: str
    model: str


class HealthResponse(BaseModel):
    status: str
    version: str


# -- Audit stats ---------------------------------------------------------------


class TopAgentResponse(BaseModel):
    name: str
    count: int
    avg_duration_ms: int


class AuditStatsResponse(BaseModel):
    total_runs: int
    success_rate: float
    total_tokens: int
    avg_duration_ms: int
    top_agents: list[TopAgentResponse]


# -- System / Doctor -----------------------------------------------------------


class DoctorCheck(BaseModel):
    name: str
    status: str  # "ok" | "warn" | "fail"
    message: str


class DoctorResponse(BaseModel):
    checks: list[DoctorCheck]


class ToolTypeResponse(BaseModel):
    name: str
    description: str


# -- Builder -------------------------------------------------------------------


class TemplateInfo(BaseModel):
    name: str
    description: str


class EnvVarStatus(BaseModel):
    name: str
    is_set: bool


class TemplateSetup(BaseModel):
    steps: list[str]
    env_vars: list[EnvVarStatus]
    extras: list[str]
    docs_url: str


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


class BuilderOptionsResponse(BaseModel):
    templates: list[TemplateInfo]
    providers: list[ProviderModels]
    detected_provider: str | None = None
    detected_model: str | None = None
    role_dirs: list[str]
    custom_presets: list[ProviderPreset]
    ollama_models: list[str]
    ollama_base_url: str
    template_setups: dict[str, TemplateSetup] = {}


class SeedRequest(BaseModel):
    mode: Literal["template", "description", "blank"]
    template: str | None = None
    description: str | None = None
    provider: str
    model: str | None = None
    base_url: str | None = None
    api_key_env: str | None = None


class ValidationIssueResponse(BaseModel):
    field: str
    message: str
    severity: str  # "error" | "warning"


class SeedResponse(BaseModel):
    yaml_text: str
    explanation: str
    issues: list[ValidationIssueResponse]
    ready: bool


class ValidateRequest(BaseModel):
    yaml_text: str


class SaveRequest(BaseModel):
    yaml_text: str
    directory: str
    filename: str
    force: bool = False


class SaveResponse(BaseModel):
    path: str
    valid: bool
    issues: list[str]
    next_steps: list[str]
    agent_id: str


# -- Key management ------------------------------------------------------------


class SaveKeyRequest(BaseModel):
    preset: str | None = None  # e.g. "openrouter" -- uses known env var name
    base_url: str | None = None  # for custom -- derives env var name from URL
    api_key: str


class SaveKeyResponse(BaseModel):
    env_var: str


# -- InitHub -------------------------------------------------------------------


class HubSearchResultResponse(BaseModel):
    owner: str
    name: str
    description: str
    tags: list[str]
    downloads: int
    latest_version: str


class HubSearchResponse(BaseModel):
    items: list[HubSearchResultResponse]


class HubSeedRequest(BaseModel):
    ref: str  # "owner/name@version"
    provider: str
    model: str | None = None
    base_url: str | None = None
    api_key_env: str | None = None


# -- Compose: list / detail ---------------------------------------------------


class ComposeSummary(BaseModel):
    id: str
    name: str
    description: str
    service_count: int
    service_names: list[str]
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


class ComposeServiceDetail(BaseModel):
    name: str
    role_path: str
    agent_id: str | None = None
    agent_name: str | None = None
    sink: SinkDetail | None = None
    depends_on: list[str] = Field(default_factory=list)
    trigger_summary: str | None = None
    restart: RestartDetail = Field(default_factory=RestartDetail)
    health_check: HealthCheckDetail = Field(default_factory=HealthCheckDetail)
    environment_count: int = 0


class ComposeDetail(BaseModel):
    id: str
    name: str
    description: str
    path: str
    services: list[ComposeServiceDetail]
    shared_memory_enabled: bool = False
    shared_documents_enabled: bool = False


class DelegateEventResponse(BaseModel):
    timestamp: str
    source_service: str
    target_service: str
    status: str
    source_run_id: str
    compose_name: str | None = None
    reason: str | None = None
    trace: str | None = None
    payload_preview: str = ""


class ComposeStatsResponse(BaseModel):
    total_events: int
    by_status: dict[str, int] = Field(default_factory=dict)


class ComposeYamlSaveRequest(BaseModel):
    yaml_text: str


class ComposeYamlSaveResponse(BaseModel):
    path: str
    valid: bool
    issues: list[str] = Field(default_factory=list)


# -- Compose: builder ---------------------------------------------------------


class PatternInfo(BaseModel):
    name: str
    description: str
    fixed_topology: bool
    slot_names: list[str]
    min_services: int
    max_services: int | None = None


class AgentSlotOption(BaseModel):
    id: str
    name: str
    description: str
    path: str


class SlotAssignment(BaseModel):
    slot: str
    agent_id: str | None = None


class ComposeBuilderOptionsResponse(BaseModel):
    patterns: list[PatternInfo]
    agents: list[AgentSlotOption]
    providers: list[ProviderModels]
    detected_provider: str | None = None
    detected_model: str | None = None
    save_dirs: list[str]
    custom_presets: list[ProviderPreset]
    ollama_models: list[str]
    ollama_base_url: str


class ComposeSeedRequest(BaseModel):
    pattern: str
    name: str
    services: list[SlotAssignment]
    service_count: int = 3
    shared_memory: bool = False
    provider: str = "openai"
    model: str | None = None
    base_url: str | None = None
    api_key_env: str | None = None


class ComposeSeedResponse(BaseModel):
    compose_yaml: str
    role_yamls: dict[str, str]
    issues: list[ValidationIssueResponse]
    ready: bool


class ComposeValidateRequest(BaseModel):
    yaml_text: str


class ComposeValidateResponse(BaseModel):
    issues: list[ValidationIssueResponse]
    ready: bool


class ComposeSaveRequest(BaseModel):
    compose_yaml: str
    role_yamls: dict[str, str]
    directory: str
    project_name: str
    force: bool = False


class ComposeSaveResponse(BaseModel):
    path: str
    valid: bool
    issues: list[str]
    next_steps: list[str]
    compose_id: str


# -- Agent memory / sessions ---------------------------------------------------


class MemoryResponse(BaseModel):
    id: int
    content: str
    category: str
    memory_type: str
    created_at: str
    consolidated_at: str | None = None


class SessionSummaryResponse(BaseModel):
    session_id: str
    agent_name: str
    timestamp: str
    message_count: int
    preview: str


class SessionMessageResponse(BaseModel):
    role: str  # "user" | "assistant"
    content: str


class SessionDetailResponse(BaseModel):
    session_id: str
    messages: list[SessionMessageResponse]
