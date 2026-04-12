"""Agent builder, hub, and starter models."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from initrunner.dashboard.schemas._common import (
    ProviderModels,
    ProviderPreset,
    ProviderStatus,
    ValidationIssueResponse,
)

__all__ = [
    "BuilderOptionsResponse",
    "EmbeddingOption",
    "EmbeddingWarning",
    "EnvVarStatus",
    "HubSearchResponse",
    "HubSearchResultResponse",
    "HubSeedRequest",
    "SaveRequest",
    "SaveResponse",
    "SeedRequest",
    "SeedResponse",
    "SetEmbeddingProviderRequest",
    "StarterInfo",
    "StartersResponse",
    "TemplateInfo",
    "TemplateSetup",
    "ValidateRequest",
]


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
    kind: str = "Agent"  # Agent, Team, or Flow


class StartersResponse(BaseModel):
    starters: list[StarterInfo]


class SeedRequest(BaseModel):
    mode: Literal["template", "description", "blank", "starter", "langchain", "pydanticai"]
    name: str
    template: str | None = None
    description: str | None = None
    starter_slug: str | None = None
    langchain_source: str | None = None
    pydanticai_source: str | None = None
    provider: str
    model: str | None = None
    base_url: str | None = None
    api_key_env: str | None = None


class EmbeddingOption(BaseModel):
    """An available embedding provider the user can choose."""

    provider: str  # "openai", "google", "ollama"
    env_var: str  # "OPENAI_API_KEY", "GOOGLE_API_KEY", "" for ollama
    is_configured: bool  # key is set / ollama running


class EmbeddingWarning(BaseModel):
    """Warning when the generated YAML needs embeddings but the effective provider is unusable."""

    llm_provider: str  # user's LLM provider (e.g. "xai")
    feature: str  # "RAG", "memory", or "RAG and memory"
    current_provider: str  # effective embedding provider
    options: list[EmbeddingOption]  # available providers with status
    message: str  # human-readable explanation


class SeedResponse(BaseModel):
    yaml_text: str
    explanation: str
    issues: list[ValidationIssueResponse]
    ready: bool
    embedding_warning: EmbeddingWarning | None = None
    sidecar_source: str | None = None
    import_warnings: list[str] = Field(default_factory=list)


class SetEmbeddingProviderRequest(BaseModel):
    yaml_text: str
    embedding_provider: str  # target provider from allowlist


class ValidateRequest(BaseModel):
    yaml_text: str


class SaveRequest(BaseModel):
    yaml_text: str
    directory: str
    filename: str
    force: bool = False
    sidecar_source: str | None = None


class SaveResponse(BaseModel):
    path: str
    valid: bool
    issues: list[str]
    next_steps: list[str]
    agent_id: str
    generated_assets: list[str] = Field(default_factory=list)


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
