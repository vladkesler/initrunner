"""Pydantic models for team YAML definitions."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from initrunner.agent.schema.base import ApiVersion, Metadata, ModelConfig
from initrunner.agent.schema.ingestion import ChunkingConfig, EmbeddingConfig
from initrunner.agent.schema.observability import ObservabilityConfig
from initrunner.agent.schema.role import parse_tool_list
from initrunner.agent.schema.tools import ToolConfig
from initrunner.compose.schema import SharedMemoryConfig
from initrunner.stores.base import StoreBackend


class PersonaConfig(BaseModel):
    """Extended persona definition with optional overrides."""

    role: str
    model: ModelConfig | None = None
    tools: list[ToolConfig] = []
    tools_mode: Literal["extend", "replace"] = "extend"
    environment: dict[str, str] = {}

    @field_validator("tools", mode="before")
    @classmethod
    def _parse_tools(cls, v: Any) -> list:
        return parse_tool_list(v)


class TeamDocumentsConfig(BaseModel):
    """Team-level shared document/RAG configuration with ingest sources."""

    enabled: bool = False
    sources: list[str] = []
    store_path: str | None = None
    store_backend: StoreBackend = StoreBackend.LANCEDB
    embeddings: EmbeddingConfig = EmbeddingConfig()
    chunking: ChunkingConfig = ChunkingConfig()

    @model_validator(mode="after")
    def _validate_embeddings_when_enabled(self) -> TeamDocumentsConfig:
        if self.enabled:
            if not self.embeddings.provider:
                raise ValueError("shared_documents.embeddings.provider is required when enabled")
            if not self.embeddings.model:
                raise ValueError("shared_documents.embeddings.model is required when enabled")
        return self


class TeamGuardrails(BaseModel):
    """Per-persona guardrails plus cumulative team-level budgets."""

    # Per-persona (passed to each execute_run via Guardrails)
    max_tokens_per_run: Annotated[int, Field(gt=0)] = 50000
    max_tool_calls: Annotated[int, Field(ge=0)] = 20
    timeout_seconds: Annotated[int, Field(gt=0)] = 300

    # Cumulative team-level budgets
    team_token_budget: Annotated[int, Field(gt=0)] | None = None
    team_timeout_seconds: Annotated[int, Field(gt=0)] | None = None


class TeamSpec(BaseModel):
    model: ModelConfig
    personas: dict[str, PersonaConfig] = Field(min_length=2)
    tools: list[ToolConfig] = []
    guardrails: TeamGuardrails = TeamGuardrails()
    handoff_max_chars: Annotated[int, Field(gt=0)] = 4000
    shared_memory: SharedMemoryConfig = SharedMemoryConfig()
    shared_documents: TeamDocumentsConfig = TeamDocumentsConfig()
    observability: ObservabilityConfig | None = None
    strategy: Literal["sequential", "parallel"] = "sequential"

    @field_validator("personas", mode="before")
    @classmethod
    def _normalize_personas(cls, v: Any) -> Any:
        if not isinstance(v, dict):
            return v
        normalized = {}
        for name, value in v.items():
            if isinstance(value, str):
                normalized[name] = {"role": value}
            else:
                normalized[name] = value
        return normalized

    @field_validator("tools", mode="before")
    @classmethod
    def _parse_tools(cls, v: Any) -> list:
        return parse_tool_list(v)

    @model_validator(mode="after")
    def _validate_persona_names(self) -> TeamSpec:
        import re

        pattern = re.compile(r"^[a-z0-9][a-z0-9-]*[a-z0-9]$")
        for name in self.personas:
            if not pattern.match(name):
                raise ValueError(
                    f"Invalid persona name '{name}': "
                    f"must match ^[a-z0-9][a-z0-9-]*[a-z0-9]$ "
                    f"(lowercase, hyphens, no leading/trailing hyphens)"
                )
        return self

    @model_validator(mode="after")
    def _validate_parallel_no_persona_env(self) -> TeamSpec:
        if self.strategy == "parallel":
            for name, persona in self.personas.items():
                if persona.environment:
                    raise ValueError(
                        f"Per-persona environment variables are not supported with "
                        f"strategy='parallel' (persona '{name}'). "
                        f"os.environ is process-global; concurrent env mutations are unsafe."
                    )
        return self


class TeamDefinition(BaseModel):
    apiVersion: ApiVersion
    kind: Literal["Team"]
    metadata: Metadata
    spec: TeamSpec
