"""Team list, detail, execution, and builder models."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from initrunner.dashboard.schemas._common import (
    AgentSlotOption,
    ItemSummary,
    ProviderModels,
    ProviderPreset,
    ValidationIssueResponse,
)

__all__ = [
    "PersonaDetail",
    "PersonaSeedEntry",
    "PersonaSeedModel",
    "PersonaStepResponse",
    "TeamBuilderOptionsResponse",
    "TeamDetail",
    "TeamRunRequest",
    "TeamRunResponse",
    "TeamSaveRequest",
    "TeamSaveResponse",
    "TeamSeedRequest",
    "TeamSeedResponse",
    "TeamSummary",
    "TeamValidateRequest",
    "TeamValidateResponse",
    "TeamYamlSaveRequest",
    "TeamYamlSaveResponse",
]


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
    debate: dict | None = None  # {max_rounds, synthesize} when strategy=debate
    features: list[str] = []


# -- Team: run -----------------------------------------------------------------


class TeamRunRequest(BaseModel):
    prompt: str


class PersonaStepResponse(BaseModel):
    persona_name: str
    step_kind: str = "persona"  # "persona" | "synthesis"
    round_num: int | None = None
    max_rounds: int | None = None
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
    mode: Literal["blank", "starter"] = "blank"
    name: str
    strategy: str = "sequential"
    persona_count: int = 2
    personas: list[PersonaSeedEntry] | None = None
    provider: str
    model: str | None = None
    base_url: str | None = None
    api_key_env: str | None = None
    debate_max_rounds: int = 3
    debate_synthesize: bool = True
    starter_slug: str | None = None


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
