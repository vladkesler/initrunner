"""Consolidation: extract durable semantic facts from episodic memories."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from initrunner.agent.schema import RoleDefinition
    from initrunner.stores.base import MemoryStoreBase

_logger = logging.getLogger(__name__)

_CONSOLIDATION_PROMPT = """\
You are a memory consolidation assistant. Below are episodic memories (things that happened).
Extract durable facts, insights, or patterns that would be useful to remember long-term.

Output each extracted insight on its own line in the format:
CATEGORY: content

Where CATEGORY is a lowercase single-word category (e.g. preference, fact, pattern, workflow).
Only output lines in that format. If there are no useful insights to extract, output nothing.

Episodes:
{episodes}
"""


def maybe_consolidate(
    memory_store: MemoryStoreBase,
    role: RoleDefinition,
    *,
    force: bool = False,
) -> int:
    """Run consolidation if enabled. Returns number of semantic memories created. Never raises."""
    try:
        return _consolidate_inner(memory_store, role, force=force)
    except Exception:
        _logger.warning("Memory consolidation failed", exc_info=True)
        return 0


def _consolidate_inner(
    memory_store: MemoryStoreBase,
    role: RoleDefinition,
    *,
    force: bool = False,
) -> int:
    if role.spec.memory is None:
        return 0
    config = role.spec.memory.consolidation
    if not config.enabled and not force:
        return 0

    episodes = memory_store.get_unconsolidated_episodes(limit=config.max_episodes_per_run)
    if not episodes:
        return 0

    # Format episodes for the LLM
    episode_texts: list[str] = []
    for ep in episodes:
        episode_texts.append(f"- [{ep.category}] ({ep.created_at}) {ep.content}")
    episodes_block = "\n".join(episode_texts)

    prompt = _CONSOLIDATION_PROMPT.format(episodes=episodes_block)

    # Lazy import — this module is only loaded when consolidation runs
    from pydantic_ai import Agent

    model_str = config.model_override or role.spec.model.to_model_string()
    consolidation_agent = Agent(model_str)
    result = consolidation_agent.run_sync(prompt)
    raw_output = result.output if hasattr(result, "output") else str(result.data)

    # Parse CATEGORY: content lines
    extracted: list[tuple[str, str]] = []
    for line in raw_output.strip().splitlines():
        line = line.strip()
        if ":" not in line:
            continue
        cat, _, content = line.partition(":")
        cat = cat.strip().lower()
        content = content.strip()
        if cat and content and cat.isalpha():
            extracted.append((cat, content))

    if not extracted:
        return 0

    # Store extracted semantic memories
    from initrunner.ingestion.embeddings import embed_single as _embed_single
    from initrunner.stores.base import MemoryType

    embed_provider = role.spec.memory.embeddings.provider or role.spec.model.provider or "openai"
    embed_model = role.spec.memory.embeddings.model
    embed_base_url = role.spec.memory.embeddings.base_url
    embed_api_key_env = role.spec.memory.embeddings.api_key_env

    created = 0
    for cat, content in extracted:
        embedding = _embed_single(
            embed_provider,
            embed_model,
            content,
            base_url=embed_base_url,
            api_key_env=embed_api_key_env,
            input_type="document",
        )
        memory_store.add_memory(
            content,
            cat,
            embedding,
            memory_type=MemoryType.SEMANTIC,
            metadata={"source": "consolidation"},
        )
        created += 1

    # Mark episodes as consolidated only after all stores succeed
    now = datetime.now(UTC).isoformat()
    memory_store.mark_consolidated([ep.id for ep in episodes], now)

    _logger.info("Consolidated %d episodes into %d semantic memories", len(episodes), created)
    return created
