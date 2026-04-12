"""Document ingestion models."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

__all__ = [
    "AddUrlRequest",
    "IngestDocumentResponse",
    "IngestFileResultResponse",
    "IngestStatsResponse",
    "IngestSummaryResponse",
]


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
