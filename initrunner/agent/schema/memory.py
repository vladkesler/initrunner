"""Memory system configuration."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, model_validator

from initrunner.agent.schema.ingestion import EmbeddingConfig
from initrunner.stores.base import StoreBackend


class EpisodicMemoryConfig(BaseModel):
    enabled: bool = True
    max_episodes: int = 500


class SemanticMemoryConfig(BaseModel):
    enabled: bool = True
    max_memories: int = 1000


class ProceduralMemoryConfig(BaseModel):
    enabled: bool = True
    max_procedures: int = 100


class ConsolidationConfig(BaseModel):
    enabled: bool = True
    interval: Literal["after_session", "after_autonomous", "manual"] = "after_session"
    max_episodes_per_run: int = 20
    model_override: str | None = None  # defaults to agent's model


class MemoryConfig(BaseModel):
    store_path: str | None = None  # default: ~/.initrunner/memory/{agent-name}.db
    store_backend: StoreBackend = StoreBackend.LANCEDB
    max_sessions: int = 10
    max_resume_messages: int = 20  # limit history loaded on --resume
    embeddings: EmbeddingConfig = EmbeddingConfig()
    episodic: EpisodicMemoryConfig = EpisodicMemoryConfig()
    semantic: SemanticMemoryConfig = SemanticMemoryConfig()
    procedural: ProceduralMemoryConfig = ProceduralMemoryConfig()
    consolidation: ConsolidationConfig = ConsolidationConfig()

    @model_validator(mode="before")
    @classmethod
    def _reject_legacy_max_memories(cls, data: dict) -> dict:
        if isinstance(data, dict) and "max_memories" in data:
            from initrunner.deprecations import REMOVED_FIELD_MESSAGE_MAX_MEMORIES

            raise ValueError(REMOVED_FIELD_MESSAGE_MAX_MEMORIES)
        return data
