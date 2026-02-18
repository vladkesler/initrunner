"""Factory functions for creating store instances."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING

from initrunner.stores.base import (
    DocumentStore,
    MemoryStoreBase,
    StoreBackend,
    resolve_memory_path,
)

if TYPE_CHECKING:
    from initrunner.agent.schema.memory import MemoryConfig


def create_document_store(
    backend: StoreBackend = StoreBackend.SQLITE_VEC,
    db_path: Path = Path(),
    dimensions: int | None = None,
) -> DocumentStore:
    """Create a DocumentStore for the given backend."""
    if backend == StoreBackend.SQLITE_VEC:
        from initrunner.stores.sqlite_vec import SqliteVecDocumentStore

        return SqliteVecDocumentStore(db_path, dimensions=dimensions)
    raise ValueError(f"Unknown document store backend: {backend}")


def create_memory_store(
    backend: StoreBackend = StoreBackend.SQLITE_VEC,
    db_path: Path = Path(),
    dimensions: int | None = None,
) -> MemoryStoreBase:
    """Create a MemoryStoreBase for the given backend."""
    if backend == StoreBackend.SQLITE_VEC:
        from initrunner.stores.sqlite_vec import SqliteVecMemoryStore

        return SqliteVecMemoryStore(db_path, dimensions=dimensions)
    raise ValueError(f"Unknown memory store backend: {backend}")


@contextmanager
def open_memory_store(
    memory_config: MemoryConfig | None,
    agent_name: str,
    *,
    dimensions: int | None = None,
    require_exists: bool = True,
) -> Iterator[MemoryStoreBase | None]:
    """Context manager for role memory store access.

    Yields the store, or ``None`` if:
    - *memory_config* is ``None`` (memory not configured)
    - *require_exists* is ``True`` and the DB file doesn't exist
    """
    if memory_config is None:
        yield None
        return
    mem_path = resolve_memory_path(memory_config.store_path, agent_name)
    if require_exists and not mem_path.exists():
        yield None
        return
    with create_memory_store(memory_config.store_backend, mem_path, dimensions=dimensions) as store:
        yield store
