"""Factory functions for creating store instances."""

from __future__ import annotations

import threading
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

# ---------------------------------------------------------------------------
# Active memory-store registry
# ---------------------------------------------------------------------------
# When a long-lived owner (e.g. ``command_context``) opens a memory store it
# registers it here.  Subsequent callers (tools, system-prompt callbacks) get
# back the *same* instance via ``acquire()`` so that zvec collection locks are
# not violated.  ``close()`` on borrowed references is a ref-counted no-op —
# only the final owner actually releases the underlying collections.

_active_memory_stores: dict[str, MemoryStoreBase] = {}
_registry_lock = threading.Lock()


def register_memory_store(db_path: Path, store: MemoryStoreBase) -> None:
    """Register an already-open store so subsequent callers reuse it."""
    with _registry_lock:
        _active_memory_stores[str(db_path)] = store


def unregister_memory_store(db_path: Path) -> None:
    """Remove a store from the registry (called on cleanup)."""
    with _registry_lock:
        _active_memory_stores.pop(str(db_path), None)


def create_document_store(
    backend: StoreBackend = StoreBackend.ZVEC,
    db_path: Path = Path(),
    dimensions: int | None = None,
) -> DocumentStore:
    """Create a DocumentStore for the given backend."""
    from initrunner.stores.zvec_store import ZvecDocumentStore

    return ZvecDocumentStore(db_path, dimensions=dimensions)


def create_memory_store(
    backend: StoreBackend = StoreBackend.ZVEC,
    db_path: Path = Path(),
    dimensions: int | None = None,
) -> MemoryStoreBase:
    """Create or reuse a MemoryStoreBase for the given backend.

    If a store for *db_path* is already registered (via
    :func:`register_memory_store`), it is returned with its reference count
    incremented so that the caller's ``close()`` won't release the underlying
    collections.
    """
    key = str(db_path)
    with _registry_lock:
        existing = _active_memory_stores.get(key)
        if existing is not None:
            existing.acquire()  # type: ignore[attr-defined]
            return existing

    from initrunner.stores.zvec_store import ZvecMemoryStore

    return ZvecMemoryStore(db_path, dimensions=dimensions)


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
