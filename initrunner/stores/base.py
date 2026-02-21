"""Abstract base classes and shared types for vector stores."""

from __future__ import annotations

import abc
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pydantic_ai.messages import ModelMessage


class StoreBackend(StrEnum):
    ZVEC = "zvec"


class MemoryType(StrEnum):
    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    PROCEDURAL = "procedural"


@dataclass(frozen=True)
class StoreConfig:
    """Narrow config for tools that read/write the document store."""

    db_path: Path
    embed_provider: str
    embed_model: str
    store_backend: StoreBackend = StoreBackend.ZVEC
    chunking_strategy: str = "fixed"
    chunk_size: int = 512
    chunk_overlap: int = 50
    embed_base_url: str = ""
    embed_api_key_env: str = ""


class DimensionMismatchError(Exception):
    """Raised when caller passes dimensions that conflict with an existing store."""


@dataclass
class SearchResult:
    chunk_id: int
    text: str
    source: str
    distance: float


@dataclass
class Memory:
    id: int
    content: str
    category: str
    created_at: str
    memory_type: MemoryType = MemoryType.SEMANTIC
    metadata: dict | None = None
    consolidated_at: str | None = None


class _LazyDir:
    """Lazy-evaluated default directory to avoid import-time filesystem access."""

    def __init__(self, getter_name: str) -> None:
        self._getter_name = getter_name
        self._value: Path | None = None

    def __fspath__(self) -> str:
        return str(self._resolve())

    def _resolve(self) -> Path:
        if self._value is None:
            from initrunner import config

            self._value = getattr(config, self._getter_name)()
        return self._value

    def __truediv__(self, other: str) -> Path:
        return self._resolve() / other

    def __str__(self) -> str:
        return str(self._resolve())

    def __repr__(self) -> str:
        return f"_LazyDir({self._getter_name!r})"

    def __getattr__(self, name: str):
        # Delegate any attribute access to the resolved Path
        return getattr(self._resolve(), name)


DEFAULT_STORES_DIR: _LazyDir | Path = _LazyDir("get_stores_dir")
DEFAULT_MEMORY_DIR: _LazyDir | Path = _LazyDir("get_memory_dir")


class EmbeddingModelChangedError(Exception):
    """Raised when the embedding model has changed and the store must be wiped."""


def resolve_store_path(store_path: str | None, agent_name: str) -> Path:
    """Resolve the document store path from config or default."""
    return Path(store_path) if store_path else DEFAULT_STORES_DIR / f"{agent_name}.zvec"


def resolve_memory_path(store_path: str | None, agent_name: str) -> Path:
    """Resolve the memory store path from config or default."""
    return Path(store_path) if store_path else DEFAULT_MEMORY_DIR / f"{agent_name}.zvec"


class FileMetadataStore(abc.ABC):
    """Abstract interface for ingestion file-metadata tracking."""

    @abc.abstractmethod
    def get_file_metadata(self, source: str) -> tuple[str, float, str] | None: ...

    @abc.abstractmethod
    def upsert_file_metadata(
        self,
        source: str,
        content_hash: str,
        last_modified: float,
        ingested_at: str,
        chunk_count: int,
    ) -> None: ...

    @abc.abstractmethod
    def delete_file_metadata(self, source: str) -> None: ...

    @abc.abstractmethod
    def list_sources(self) -> list[str]: ...

    @abc.abstractmethod
    def list_file_hashes(self) -> dict[str, str]:
        """Return {source: content_hash} for all tracked files."""
        ...


class DocumentStore(FileMetadataStore):
    """Abstract interface for document vector stores.

    Inherits :class:`FileMetadataStore` so that a single store instance
    satisfies both narrow (query-only) and wide (ingestion) consumers.
    Read-only consumers can type-hint with ``DocumentStore`` directly;
    ingestion code that only needs metadata can accept ``FileMetadataStore``.
    """

    @property
    @abc.abstractmethod
    def dimensions(self) -> int | None: ...

    @abc.abstractmethod
    def add_documents(
        self,
        texts: list[str],
        embeddings: list[list[float]],
        sources: list[str],
        ingested_at: str = "",
    ) -> None: ...

    @abc.abstractmethod
    def query(
        self,
        embedding: list[float],
        top_k: int = 5,
        source_filter: str | None = None,
    ) -> list[SearchResult]: ...

    @abc.abstractmethod
    def count(self) -> int: ...

    @abc.abstractmethod
    def delete_by_source(self, source: str) -> int: ...

    @abc.abstractmethod
    def replace_source(
        self,
        source: str,
        texts: list[str],
        embeddings: list[list[float]],
        ingested_at: str,
        content_hash: str,
        last_modified: float,
    ) -> int: ...

    @abc.abstractmethod
    def read_store_meta(self, key: str) -> str | None: ...

    @abc.abstractmethod
    def write_store_meta(self, key: str, value: str) -> None: ...

    @abc.abstractmethod
    def close(self) -> None: ...

    def __enter__(self) -> DocumentStore:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


@dataclass(frozen=True)
class SessionSummary:
    """Lightweight summary of a stored session for listing."""

    session_id: str
    agent_name: str
    timestamp: str
    message_count: int
    preview: str  # first 80 chars of first user message


class SessionStore(abc.ABC):
    """Abstract interface for session persistence."""

    @abc.abstractmethod
    def save_session(
        self, session_id: str, agent_name: str, messages: list[ModelMessage]
    ) -> None: ...

    @abc.abstractmethod
    def load_latest_session(
        self, agent_name: str, max_messages: int = 20
    ) -> list[ModelMessage] | None: ...

    @abc.abstractmethod
    def prune_sessions(self, agent_name: str, keep_count: int = 10) -> int: ...

    @abc.abstractmethod
    def list_sessions(self, agent_name: str, limit: int = 20) -> list[SessionSummary]: ...

    @abc.abstractmethod
    def load_session_by_id(
        self, session_id: str, agent_name: str, max_messages: int = 20
    ) -> list[ModelMessage] | None: ...

    @abc.abstractmethod
    def delete_session(self, session_id: str, agent_name: str) -> bool: ...


class MemoryStore(abc.ABC):
    """Abstract interface for long-term memories."""

    @abc.abstractmethod
    def add_memory(
        self,
        content: str,
        category: str,
        embedding: list[float],
        *,
        memory_type: MemoryType = MemoryType.SEMANTIC,
        metadata: dict | None = None,
    ) -> int: ...

    @abc.abstractmethod
    def search_memories(
        self,
        embedding: list[float],
        top_k: int = 5,
        *,
        memory_types: list[MemoryType] | None = None,
    ) -> list[tuple[Memory, float]]: ...

    @abc.abstractmethod
    def list_memories(
        self,
        category: str | None = None,
        limit: int = 20,
        *,
        memory_type: MemoryType | None = None,
    ) -> list[Memory]: ...

    @abc.abstractmethod
    def count_memories(self, *, memory_type: MemoryType | None = None) -> int: ...

    @abc.abstractmethod
    def prune_memories(
        self, keep_count: int = 1000, *, memory_type: MemoryType | None = None
    ) -> int: ...

    @abc.abstractmethod
    def mark_consolidated(self, memory_ids: list[int], consolidated_at: str) -> None: ...

    @abc.abstractmethod
    def get_unconsolidated_episodes(self, limit: int = 20) -> list[Memory]: ...


class MemoryStoreBase(SessionStore, MemoryStore):
    """Combined interface for stores that support both sessions and memories."""

    @property
    @abc.abstractmethod
    def dimensions(self) -> int | None: ...

    @abc.abstractmethod
    def close(self) -> None: ...

    def __enter__(self) -> MemoryStoreBase:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()
