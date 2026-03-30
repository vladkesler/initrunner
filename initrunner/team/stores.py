"""Synthesize minimal RoleDefinitions from team shared configs for store access."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from initrunner.agent.schema.role import RoleDefinition
    from initrunner.team.schema import TeamDefinition


def resolve_team_memory_role(team: TeamDefinition) -> RoleDefinition | None:
    """Build a RoleDefinition whose memory config points at the team's shared store.

    Returns ``None`` if ``shared_memory`` is disabled.
    """
    if not team.spec.shared_memory.enabled:
        return None

    from initrunner.agent.schema.memory import MemoryConfig
    from initrunner.stores.base import DEFAULT_MEMORY_DIR

    store_path = team.spec.shared_memory.store_path or str(
        DEFAULT_MEMORY_DIR / f"{team.metadata.name}-shared.db"
    )

    return _make_role(
        team,
        memory=MemoryConfig(
            store_path=store_path,
            store_backend=team.spec.shared_memory.store_backend,
            semantic=MemoryConfig().semantic.model_copy(
                update={"max_memories": team.spec.shared_memory.max_memories},
            ),
        ),
    )


def resolve_team_ingest_role(team: TeamDefinition) -> RoleDefinition | None:
    """Build a RoleDefinition whose ingest config points at the team's shared store.

    Returns ``None`` if ``shared_documents`` is disabled.
    """
    if not team.spec.shared_documents.enabled:
        return None

    from initrunner.agent.schema.ingestion import IngestConfig
    from initrunner.stores.base import DEFAULT_STORES_DIR

    store_path = team.spec.shared_documents.store_path or str(
        DEFAULT_STORES_DIR / f"{team.metadata.name}-shared.lance"
    )

    return _make_role(
        team,
        ingest=IngestConfig(
            sources=team.spec.shared_documents.sources,
            store_path=store_path,
            store_backend=team.spec.shared_documents.store_backend,
            embeddings=team.spec.shared_documents.embeddings,
            chunking=team.spec.shared_documents.chunking,
        ),
    )


def _make_role(
    team: TeamDefinition,
    *,
    memory: object | None = None,
    ingest: object | None = None,
) -> RoleDefinition:
    """Construct a minimal RoleDefinition for store I/O."""
    from initrunner.agent.schema.base import ApiVersion, Kind
    from initrunner.agent.schema.role import AgentSpec, RoleDefinition, RoleMetadata

    return RoleDefinition(
        apiVersion=ApiVersion.V1,
        kind=Kind.AGENT,
        metadata=RoleMetadata(name=team.metadata.name),
        spec=AgentSpec(
            role="",
            model=team.spec.model,
            memory=memory,  # type: ignore[arg-type]
            ingest=ingest,  # type: ignore[arg-type]
        ),
    )
