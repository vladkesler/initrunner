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
    """Which embedding model produces the vectors for a store.

    ``provider`` selects the backend. ``local`` runs an in-process fastembed
    model with no HTTP hop (offline-friendly, no API key, requires the
    ``local-embeddings`` extra). It is distinct from ``ollama``, which routes
    through an OpenAI-compatible HTTP client and needs a running endpoint.

    Dimension consistency: a store is fixed to the dimension of the model that
    first wrote to it. Changing ``provider`` or ``model`` to one with a
    different dimension (for example ``BAAI/bge-small-en-v1.5`` at 384 to
    ``BAAI/bge-base-en-v1.5`` at 768) requires a fresh ``store_path``.
    """

    # empty provider = derive from spec.model.provider; 'local' = fastembed in-process
    provider: str = ""
    # empty model = provider default (e.g. text-embedding-3-small, or bge-small for local)
    model: str = ""
    # base_url/api_key_env: empty = provider default; set for custom endpoints; unused for 'local'
    base_url: str = ""
    api_key_env: str = ""


class RetrieverConfig(BaseModel):
    """How ingested documents are searched at query time.

    ``vector`` is dense cosine search only (the default, unchanged behaviour).
    ``hybrid`` fuses dense vector search with BM25 full-text search using
    reciprocal rank fusion (RRF). ``hybrid_rerank`` runs the hybrid stage and
    then reorders the fused candidates with a cross-encoder model. The
    cross-encoder backend is optional: when ``sentence-transformers`` is not
    installed, ``hybrid_rerank`` degrades to plain ``hybrid`` scoring.
    """

    strategy: Literal["vector", "hybrid", "hybrid_rerank"] = "vector"
    rrf_k: int = 60  # RRF smoothing constant; lancedb default
    reranker_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"


class IngestConfig(BaseModel):
    auto: bool = True
    sources: list[str]
    watch: bool = False
    chunking: ChunkingConfig = ChunkingConfig()
    embeddings: EmbeddingConfig = EmbeddingConfig()
    retriever: RetrieverConfig = RetrieverConfig()
    store_backend: StoreBackend = StoreBackend.LANCEDB
    store_path: str | None = None  # default: ~/.initrunner/stores/{agent-name}.db
