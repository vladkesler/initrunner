"""Stores shared by agents that run together.

Teams, flows and groups all let several agents read and write one memory or
document store. The wiring is the same in every case: point each member's own
memory/ingest config at the shared path before its agent is built.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from initrunner.agent.schema.role import RoleDefinition


class SharedMemorySettings(Protocol):
    """The shared-memory fields every composition config has."""

    enabled: bool
    store_path: str | None
    max_memories: int


class SharedDocumentSettings(Protocol):
    """The shared-document fields every composition config has."""

    enabled: bool
    store_path: str | None
    store_backend: Any
    embeddings: Any


def apply_shared_memory(role: RoleDefinition, store_path: str, max_memories: int = 1000) -> None:
    """Patch a role's memory config to point at a shared store.

    If the role already has memory configured, override ``store_path`` and
    ``semantic.max_memories``.  Otherwise inject a new ``MemoryConfig``.
    """
    from initrunner.agent.schema.memory import MemoryConfig, SemanticMemoryConfig

    if role.spec.memory is not None:
        updated_semantic = role.spec.memory.semantic.model_copy(
            update={"max_memories": max_memories}
        )
        role.spec.memory = role.spec.memory.model_copy(
            update={"store_path": store_path, "semantic": updated_semantic}
        )
    else:
        role.spec.memory = MemoryConfig(
            store_path=store_path,
            semantic=SemanticMemoryConfig(max_memories=max_memories),
        )


def apply_shared_documents(
    role: RoleDefinition, cfg: SharedDocumentSettings, store_path: str
) -> None:
    """Inject a shared document store into *role* so a ``retrieval``
    retrieval tool is registered.
    """
    from initrunner.agent.schema.ingestion import IngestConfig

    if role.spec.ingest is not None:
        role.spec.ingest = role.spec.ingest.model_copy(
            update={
                "store_path": store_path,
                "store_backend": cfg.store_backend,
                "embeddings": cfg.embeddings,
            }
        )
    else:
        role.spec.ingest = IngestConfig(
            sources=[],
            store_path=store_path,
            store_backend=cfg.store_backend,
            embeddings=cfg.embeddings,
        )


def resolve_shared_store_paths(
    owner_name: str,
    shared_memory: SharedMemorySettings,
    shared_documents: SharedDocumentSettings,
) -> tuple[str | None, str | None]:
    """Store paths for shared memory and shared documents, or ``None`` if off.

    Defaults are derived from the team, flow or group name so agents running
    together land in one store without anyone configuring a path.
    """
    from initrunner.stores.base import DEFAULT_MEMORY_DIR, DEFAULT_STORES_DIR

    memory_path: str | None = None
    document_path: str | None = None

    if shared_memory.enabled:
        memory_path = shared_memory.store_path or str(
            DEFAULT_MEMORY_DIR / f"{owner_name}-shared.db"
        )
    if shared_documents.enabled:
        document_path = shared_documents.store_path or str(
            DEFAULT_STORES_DIR / f"{owner_name}-shared.lance"
        )

    return memory_path, document_path
