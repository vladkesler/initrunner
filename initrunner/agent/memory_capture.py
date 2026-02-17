"""Episodic memory auto-capture for autonomous and daemon runs."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from initrunner.agent.schema import RoleDefinition
    from initrunner.stores.base import MemoryStoreBase

_logger = logging.getLogger(__name__)


def capture_episode(
    memory_store: MemoryStoreBase,
    role: RoleDefinition,
    summary: str,
    *,
    category: str = "autonomous_run",
    metadata: dict | None = None,
    trigger_type: str | None = None,
) -> None:
    """Persist an episodic memory from a run result. Never raises."""
    try:
        if role.spec.memory is None:
            return
        if not role.spec.memory.episodic.enabled:
            return

        from initrunner.ingestion.embeddings import embed_single as _embed_single
        from initrunner.stores.base import MemoryType

        embed_provider = (
            role.spec.memory.embeddings.provider or role.spec.model.provider or "openai"
        )
        embed_model = role.spec.memory.embeddings.model
        embed_base_url = role.spec.memory.embeddings.base_url
        embed_api_key_env = role.spec.memory.embeddings.api_key_env

        embedding = _embed_single(
            embed_provider,
            embed_model,
            summary,
            base_url=embed_base_url,
            api_key_env=embed_api_key_env,
            input_type="document",
        )

        episode_meta = dict(metadata or {})
        if trigger_type:
            episode_meta["trigger_type"] = trigger_type

        memory_store.add_memory(
            summary,
            category,
            embedding,
            memory_type=MemoryType.EPISODIC,
            metadata=episode_meta if episode_meta else None,
        )
        memory_store.prune_memories(
            role.spec.memory.episodic.max_episodes, memory_type=MemoryType.EPISODIC
        )
    except Exception:
        _logger.warning("Failed to capture episodic memory", exc_info=True)
