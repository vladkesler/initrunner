"""Pydantic response/request schemas for the dashboard API."""

from __future__ import annotations

from pydantic import BaseModel

# --- Roles ---


class RoleSummary(BaseModel):
    id: str
    path: str
    name: str
    description: str
    model: str
    features: list[str]
    valid: bool
    error: str | None = None


class ToolSummary(BaseModel):
    type: str
    summary: str


class TriggerSummary(BaseModel):
    type: str
    summary: str


class SinkSummary(BaseModel):
    type: str
    summary: str


class ModelDetail(BaseModel):
    provider: str
    name: str
    base_url: str | None = None
    temperature: float
    max_tokens: int


class GuardrailsDetail(BaseModel):
    max_tokens_per_run: int
    timeout_seconds: int
    max_tool_calls: int
    max_request_limit: int | None = None
    input_tokens_limit: int | None = None
    total_tokens_limit: int | None = None
    session_token_budget: int | None = None
    daemon_token_budget: int | None = None
    daemon_daily_token_budget: int | None = None


class IngestDetail(BaseModel):
    sources: list[str]
    chunking_strategy: str
    chunk_size: int
    chunk_overlap: int
    store_backend: str


class MemoryDetail(BaseModel):
    store_backend: str
    max_sessions: int
    max_memories: int
    max_resume_messages: int


class RoleDetail(RoleSummary):
    system_prompt: str
    model_config_detail: ModelDetail
    guardrails: GuardrailsDetail
    tools: list[ToolSummary]
    triggers: list[TriggerSummary]
    sinks: list[SinkSummary]
    ingest: IngestDetail | None = None
    memory: MemoryDetail | None = None
    yaml_content: str


class RoleListResponse(BaseModel):
    roles: list[RoleSummary]


class ValidationResponse(BaseModel):
    valid: bool
    error: str | None = None
    role: RoleSummary | None = None


class RoleUpdateRequest(BaseModel):
    field: str
    value: object


class ValidateRequest(BaseModel):
    path: str


class RoleCreateRequest(BaseModel):
    yaml_content: str


class RoleGenerateRequest(BaseModel):
    description: str
    provider: str | None = None
    name: str | None = None


class RoleYamlUpdateRequest(BaseModel):
    yaml_content: str


# --- Audit ---


class AuditRecordResponse(BaseModel):
    id: str
    agent_name: str
    run_id: str
    prompt: str
    output: str
    success: bool
    error: str | None = None
    tokens_in: int
    tokens_out: int
    total_tokens: int
    tool_calls: int
    duration_ms: int
    timestamp: str
    trigger_type: str | None = None


class AuditListResponse(BaseModel):
    records: list[AuditRecordResponse]


# --- Memory ---


class MemoryItemResponse(BaseModel):
    id: str
    content: str
    category: str
    created_at: str
    metadata: dict[str, str] = {}


class MemoryListResponse(BaseModel):
    memories: list[MemoryItemResponse]


# --- Ingest ---


class IngestSourceResponse(BaseModel):
    path: str
    name: str
    size_bytes: int


class IngestSourcesResponse(BaseModel):
    sources: list[IngestSourceResponse]
