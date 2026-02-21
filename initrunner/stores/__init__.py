"""Vector store abstractions and implementations."""

from initrunner.stores.base import (
    DEFAULT_MEMORY_DIR,
    DEFAULT_STORES_DIR,
    DimensionMismatchError,
    DocumentStore,
    EmbeddingModelChangedError,
    FileMetadataStore,
    Memory,
    MemoryStore,
    MemoryStoreBase,
    SearchResult,
    SessionStore,
    StoreBackend,
    StoreConfig,
    resolve_memory_path,
    resolve_store_path,
)
from initrunner.stores.factory import (
    create_document_store,
    create_memory_store,
    open_memory_store,
    register_memory_store,
    unregister_memory_store,
)

__all__ = [
    "DEFAULT_MEMORY_DIR",
    "DEFAULT_STORES_DIR",
    "DimensionMismatchError",
    "DocumentStore",
    "EmbeddingModelChangedError",
    "FileMetadataStore",
    "Memory",
    "MemoryStore",
    "MemoryStoreBase",
    "SearchResult",
    "SessionStore",
    "StoreBackend",
    "StoreConfig",
    "create_document_store",
    "create_memory_store",
    "open_memory_store",
    "register_memory_store",
    "unregister_memory_store",
    "resolve_memory_path",
    "resolve_store_path",
]
