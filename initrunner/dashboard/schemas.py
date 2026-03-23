"""Pydantic response/request models for the dashboard API."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


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
