"""Ingestion pipeline configuration."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, model_validator

from initrunner.stores.base import StoreBackend


class ChunkingConfig(BaseModel):
    strategy: Literal["fixed", "paragraph"] = "fixed"
    chunk_size: int = 512
    chunk_overlap: int = 50

    @model_validator(mode="after")
    def _validate_overlap(self) -> ChunkingConfig:
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError(
                f"chunk_overlap ({self.chunk_overlap}) must be less than "
                f"chunk_size ({self.chunk_size})"
            )
        return self


class EmbeddingConfig(BaseModel):
    provider: str = ""  # empty = derive from spec.model.provider
    model: str = ""  # empty = provider default (e.g. text-embedding-3-small)
    base_url: str = ""  # empty = provider default; set for custom endpoints
    api_key_env: str = ""  # env var name for API key; empty = provider default


class IngestConfig(BaseModel):
    sources: list[str]
    watch: bool = False
    chunking: ChunkingConfig = ChunkingConfig()
    embeddings: EmbeddingConfig = EmbeddingConfig()
    store_backend: StoreBackend = StoreBackend.SQLITE_VEC
    store_path: str | None = None  # default: ~/.initrunner/stores/{agent-name}.db
