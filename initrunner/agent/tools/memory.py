"""Long-term memory tools: remember, recall, list_memories, learn_procedure, record_episode."""

from __future__ import annotations

from typing import Literal

from pydantic_ai.toolsets.function import FunctionToolset

from initrunner.agent.schema.memory import MemoryConfig
from initrunner.agent.schema.security import ToolSandboxConfig
from initrunner.agent.tools.retrieval import _validate_store_path
from initrunner.ingestion.embeddings import embed_single as _embed_single


def build_memory_toolset(
    config: MemoryConfig,
    agent_name: str,
    model_provider: str,
    *,
    sandbox: ToolSandboxConfig | None = None,
) -> FunctionToolset:
    """Build the long-term memory tools: remember, recall, list_memories, etc."""
    import re

    from initrunner.stores.base import MemoryType, resolve_memory_path
    from initrunner.stores.factory import create_memory_store

    db_path = resolve_memory_path(config.store_path, agent_name)

    if sandbox is not None:
        _validate_store_path(db_path, sandbox.restrict_db_paths)

    embed_provider = config.embeddings.provider or model_provider or "openai"
    embed_model = config.embeddings.model
    embed_base_url = config.embeddings.base_url
    embed_api_key_env = config.embeddings.api_key_env
    backend = config.store_backend

    def _sanitize_category(category: str) -> str:
        return re.sub(r"[^a-z0-9]+", "_", category.lower()).strip("_") or "general"

    def _embed(
        content: str, *, input_type: Literal["query", "document"] = "document"
    ) -> list[float]:
        return _embed_single(
            embed_provider,
            embed_model,
            content,
            base_url=embed_base_url,
            api_key_env=embed_api_key_env,
            input_type=input_type,
        )

    toolset = FunctionToolset()

    if config.semantic.enabled:

        @toolset.tool
        def remember(content: str, category: str = "general") -> str:
            """Store a piece of information in long-term memory for later recall."""
            category = _sanitize_category(category)
            embedding = _embed(content)
            with create_memory_store(backend, db_path, dimensions=len(embedding)) as store:
                mem_id = store.add_memory(
                    content, category, embedding, memory_type=MemoryType.SEMANTIC
                )
                store.prune_memories(config.semantic.max_memories, memory_type=MemoryType.SEMANTIC)
            return f"Remembered (id={mem_id}, category={category})"

    @toolset.tool
    def recall(
        query: str,
        top_k: int = 5,
        memory_types: list[str] | None = None,
    ) -> str:
        """Search long-term memory for information relevant to the query.

        Args:
            query: The search query.
            top_k: Maximum number of results to return.
            memory_types: Optional filter by type (episodic, semantic, procedural).
        """
        if not db_path.exists():
            return "No memories stored yet."

        query_embedding = _embed(query, input_type="query")

        # Convert string types to MemoryType enum
        mt_filter: list[MemoryType] | None = None
        if memory_types:
            mt_filter = [MemoryType(t) for t in memory_types]

        with create_memory_store(backend, db_path) as store:
            results = store.search_memories(query_embedding, top_k=top_k, memory_types=mt_filter)

        if not results:
            return "No relevant memories found."

        parts: list[str] = []
        for mem, distance in results:
            score = 1 - distance
            parts.append(
                f"[Type: {mem.memory_type} | Category: {mem.category} | "
                f"Score: {score:.3f} | {mem.created_at}]\n{mem.content}"
            )
        return "\n\n---\n\n".join(parts)

    @toolset.tool
    def list_memories(
        category: str | None = None,
        limit: int = 20,
        memory_type: str | None = None,
    ) -> str:
        """List recent memories, optionally filtered by category or type.

        Args:
            category: Optional category filter.
            limit: Maximum number of results.
            memory_type: Optional filter by type (episodic, semantic, procedural).
        """
        if not db_path.exists():
            return "No memories stored yet."

        mt_filter = MemoryType(memory_type) if memory_type else None

        with create_memory_store(backend, db_path) as store:
            memories = store.list_memories(category=category, limit=limit, memory_type=mt_filter)

        if not memories:
            return "No memories found."

        parts: list[str] = []
        for mem in memories:
            parts.append(f"[{mem.memory_type}:{mem.category}] ({mem.created_at}) {mem.content}")
        return "\n".join(parts)

    if config.procedural.enabled:

        @toolset.tool
        def learn_procedure(content: str, category: str = "general") -> str:
            """Store a learned procedure, policy, or pattern for future reference.

            Use this to record insights about how to handle situations, best practices,
            or patterns that should be followed in future interactions.
            """
            category = _sanitize_category(category)
            embedding = _embed(content)
            with create_memory_store(backend, db_path, dimensions=len(embedding)) as store:
                mem_id = store.add_memory(
                    content, category, embedding, memory_type=MemoryType.PROCEDURAL
                )
                store.prune_memories(
                    config.procedural.max_procedures, memory_type=MemoryType.PROCEDURAL
                )
            return f"Learned procedure (id={mem_id}, category={category})"

    if config.episodic.enabled:

        @toolset.tool
        def record_episode(content: str, category: str = "general") -> str:
            """Record an episode — what happened during a task or interaction.

            Use this to capture outcomes, decisions made, errors encountered,
            or other events worth remembering.
            """
            category = _sanitize_category(category)
            embedding = _embed(content)
            with create_memory_store(backend, db_path, dimensions=len(embedding)) as store:
                mem_id = store.add_memory(
                    content, category, embedding, memory_type=MemoryType.EPISODIC
                )
                store.prune_memories(config.episodic.max_episodes, memory_type=MemoryType.EPISODIC)
            return f"Recorded episode (id={mem_id}, category={category})"

    return toolset
