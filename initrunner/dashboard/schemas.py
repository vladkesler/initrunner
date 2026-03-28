"""Pydantic response/request models for the dashboard API."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


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
    config: dict = {}


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


class DeleteResponse(BaseModel):
    """Confirmation that an entity was deleted."""

    id: str
    path: str


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


class TriggerStatResponse(BaseModel):
    """Per-trigger operational stats for the agent detail page."""

    trigger_type: str
    summary: str
    fire_count: int = 0
    success_count: int = 0
    fail_count: int = 0
    last_fire_time: str | None = None
    avg_duration_ms: int = 0
    last_error: str | None = None
    next_check_time: str | None = None


# -- System / Doctor -----------------------------------------------------------


class DoctorCheck(BaseModel):
    name: str
    status: str  # "ok" | "warn" | "fail"
    message: str


class DoctorResponse(BaseModel):
    checks: list[DoctorCheck]
    embedding_checks: list[DoctorCheck] = []


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


class ProviderStatus(BaseModel):
    provider: str
    env_var: str
    is_configured: bool


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
    provider_status: list[ProviderStatus] = []
    tool_func_map: dict[str, list[str]] = {}  # tool type -> function names


class StarterInfo(BaseModel):
    slug: str
    name: str
    description: str
    tags: list[str]
    features: list[str]


class StartersResponse(BaseModel):
    starters: list[StarterInfo]


class SeedRequest(BaseModel):
    mode: Literal["template", "description", "blank", "starter"]
    name: str
    template: str | None = None
    description: str | None = None
    starter_slug: str | None = None
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
    provider: str | None = None  # standard provider name (e.g. "openai", "anthropic")
    preset: str | None = None  # e.g. "openrouter" -- uses known env var name
    base_url: str | None = None  # for custom -- derives env var name from URL
    api_key: str
    verify: bool = False  # attempt real API call validation (openai/anthropic only)


class SaveKeyResponse(BaseModel):
    env_var: str
    validated: bool = False
    validation_supported: bool = False


class ProviderStatusResponse(BaseModel):
    providers: list[ProviderStatus]
    detected_provider: str | None = None
    detected_model: str | None = None


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


class ComposeRunRequest(BaseModel):
    prompt: str
    message_history: str | None = None


class ServiceStepResponse(BaseModel):
    service_name: str
    output: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    duration_ms: int = 0
    tool_calls: int = 0
    tool_call_names: list[str] = Field(default_factory=list)
    success: bool = True
    error: str | None = None


class ComposeRunResponse(BaseModel):
    output: str = ""
    output_mode: str = "none"
    final_service_name: str | None = None
    steps: list[ServiceStepResponse] = Field(default_factory=list)
    tokens_in: int = 0
    tokens_out: int = 0
    total_tokens: int = 0
    duration_ms: int = 0
    success: bool = True
    error: str | None = None
    message_history: str | None = None


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
    routing_strategy: Literal["all", "keyword", "sense"] | None = None


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


# -- Team: list / detail -------------------------------------------------------


class PersonaDetail(BaseModel):
    """Persona configuration for the team detail page."""

    name: str
    role: str
    model: dict | None = None  # ModelConfig serialized; None = inherits team model
    tools: list[ItemSummary] = []
    tools_mode: str = "extend"
    environment_count: int = 0


class TeamSummary(BaseModel):
    id: str
    name: str
    description: str
    strategy: str  # "sequential" | "parallel"
    persona_count: int
    persona_names: list[str]
    provider: str
    model: str
    has_model_overrides: bool
    features: list[str]
    path: str
    error: str | None = None


class TeamDetail(BaseModel):
    """Full team configuration for the detail page."""

    id: str
    name: str
    description: str
    path: str
    error: str | None = None
    strategy: str
    model: dict  # ModelConfig serialized
    personas: list[PersonaDetail]
    guardrails: dict  # TeamGuardrails serialized
    handoff_max_chars: int
    shared_memory: dict  # SharedMemoryConfig serialized
    shared_documents: dict  # TeamDocumentsConfig serialized
    tools: list[ItemSummary] = []
    observability: dict | None = None
    features: list[str] = []


# -- Team: run -----------------------------------------------------------------


class TeamRunRequest(BaseModel):
    prompt: str


class PersonaStepResponse(BaseModel):
    persona_name: str
    output: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    duration_ms: int = 0
    tool_calls: int = 0
    tool_call_names: list[str] = Field(default_factory=list)
    success: bool = True
    error: str | None = None


class TeamRunResponse(BaseModel):
    team_run_id: str
    output: str = ""
    steps: list[PersonaStepResponse] = Field(default_factory=list)
    tokens_in: int = 0
    tokens_out: int = 0
    total_tokens: int = 0
    duration_ms: int = 0
    success: bool = True
    error: str | None = None


# -- Team: builder -------------------------------------------------------------


class TeamBuilderOptionsResponse(BaseModel):
    providers: list[ProviderModels]
    agents: list[AgentSlotOption] = []
    detected_provider: str | None = None
    detected_model: str | None = None
    save_dirs: list[str]
    custom_presets: list[ProviderPreset]
    ollama_models: list[str]
    ollama_base_url: str


class PersonaSeedModel(BaseModel):
    """Model override for a persona seed entry."""

    provider: str
    name: str
    base_url: str | None = None
    api_key_env: str | None = None


class PersonaSeedEntry(BaseModel):
    """Individual persona definition for team seed requests."""

    name: str
    role: str = ""
    model: PersonaSeedModel | None = None


class TeamSeedRequest(BaseModel):
    mode: Literal["blank"]
    name: str
    strategy: str = "sequential"
    persona_count: int = 2
    personas: list[PersonaSeedEntry] | None = None
    provider: str
    model: str | None = None
    base_url: str | None = None
    api_key_env: str | None = None


class TeamSeedResponse(BaseModel):
    yaml_text: str
    explanation: str
    issues: list[ValidationIssueResponse]
    ready: bool


class TeamValidateRequest(BaseModel):
    yaml_text: str


class TeamValidateResponse(BaseModel):
    issues: list[ValidationIssueResponse]
    ready: bool


class TeamSaveRequest(BaseModel):
    yaml_text: str
    directory: str
    filename: str
    force: bool = False


class TeamSaveResponse(BaseModel):
    path: str
    valid: bool
    issues: list[str]
    next_steps: list[str]
    team_id: str


class TeamYamlSaveRequest(BaseModel):
    yaml_text: str


class TeamYamlSaveResponse(BaseModel):
    path: str
    valid: bool
    issues: list[str] = Field(default_factory=list)


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


# -- Ingestion -----------------------------------------------------------------


class IngestDocumentResponse(BaseModel):
    source: str
    chunk_count: int
    ingested_at: str
    content_hash: str
    is_url: bool
    is_managed: bool


class IngestSummaryResponse(BaseModel):
    total_documents: int
    total_chunks: int
    store_path: str
    sources_config: list[str]
    managed_count: int
    last_ingested_at: str | None = None


class IngestFileResultResponse(BaseModel):
    path: str
    status: str  # "new" | "updated" | "skipped" | "error"
    chunks: int = 0
    error: str | None = None


class IngestStatsResponse(BaseModel):
    new: int
    updated: int
    skipped: int
    errored: int
    total_chunks: int
    file_results: list[IngestFileResultResponse] = Field(default_factory=list)


class AddUrlRequest(BaseModel):
    url: str

    @field_validator("url")
    @classmethod
    def _validate_url_scheme(cls, v: str) -> str:
        from urllib.parse import urlparse

        parsed = urlparse(v)
        if parsed.scheme.lower() not in ("http", "https"):
            raise ValueError(f"Only http/https URLs allowed, got {parsed.scheme!r}")
        if not parsed.hostname:
            raise ValueError("URL must have a hostname")
        return v


# -- Skills ----------------------------------------------------------------


class RequirementStatusResponse(BaseModel):
    name: str
    kind: str  # "env" | "bin"
    met: bool
    detail: str


class SkillToolSummary(BaseModel):
    type: str
    summary: str


class SkillSummary(BaseModel):
    id: str
    name: str
    description: str
    scope: str
    has_tools: bool
    tool_count: int
    is_directory_form: bool
    requirements_met: bool
    requirement_count: int
    path: str
    error: str | None = None


class SkillAgentRef(BaseModel):
    id: str
    name: str


class SkillDetail(BaseModel):
    id: str
    name: str
    description: str
    scope: str
    path: str
    is_directory_form: bool
    has_resources: bool = False
    error: str | None = None
    license: str = ""
    compatibility: str = ""
    metadata: dict[str, str] = {}
    tools: list[SkillToolSummary] = []
    requirements: list[RequirementStatusResponse] = []
    requirements_met: bool = True
    prompt: str = ""
    prompt_preview: str = ""
    used_by_agents: list[SkillAgentRef] = []


class SkillContentResponse(BaseModel):
    content: str
    path: str


class SkillContentSaveRequest(BaseModel):
    content: str


class SkillContentSaveResponse(BaseModel):
    """Validate-before-save: valid=False means content was NOT written."""

    path: str
    valid: bool
    issues: list[str] = Field(default_factory=list)


class SkillCreateRequest(BaseModel):
    name: str
    directory: str
    provider: str = "openai"


class SkillCreateResponse(BaseModel):
    id: str
    path: str
    name: str


class SkillDeleteBlockedResponse(BaseModel):
    """Returned when delete is blocked by resource files."""

    id: str
    path: str
    blocked: bool = True
    resource_files: list[str] = Field(default_factory=list)
    message: str = ""


class SkillRef(BaseModel):
    """Resolved skill reference for agent detail cross-linking."""

    name: str
    skill_id: str | None = None
