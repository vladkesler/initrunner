"""Shared-store helpers for team mode.

Includes:
- resolve_shared_paths / run_pre_ingestion / apply_shared_stores: used by
  the graph runner to wire shared memory and document stores into persona roles.
- resolve_team_memory_role / resolve_team_ingest_role: synthesize minimal
  RoleDefinitions for direct store access (CLI inspect, etc.).
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from initrunner.agent.schema.role import RoleDefinition
    from initrunner.team.schema import TeamDefinition


# ---------------------------------------------------------------------------
# Shared-store wiring (used by graph runner)
# ---------------------------------------------------------------------------


def resolve_shared_paths(
    team: TeamDefinition,
) -> tuple[str | None, str | None]:
    """Resolve store paths for shared memory and shared documents."""
    shared_mem_path: str | None = None
    shared_doc_path: str | None = None

    if team.spec.shared_memory.enabled:
        from initrunner.stores.base import DEFAULT_MEMORY_DIR

        shared_mem_path = team.spec.shared_memory.store_path or str(
            DEFAULT_MEMORY_DIR / f"{team.metadata.name}-shared.db"
        )

    if team.spec.shared_documents.enabled:
        from initrunner.stores.base import DEFAULT_STORES_DIR

        shared_doc_path = team.spec.shared_documents.store_path or str(
            DEFAULT_STORES_DIR / f"{team.metadata.name}-shared.lance"
        )

    return shared_mem_path, shared_doc_path


def run_pre_ingestion(
    team: TeamDefinition,
    shared_doc_path: str,
    team_dir: Path,
) -> None:
    """Run the ingestion pipeline for shared documents before the persona loop."""
    from initrunner.agent.schema.ingestion import IngestConfig
    from initrunner.ingestion.pipeline import run_ingest

    ingest_config = IngestConfig(
        sources=team.spec.shared_documents.sources,
        store_path=shared_doc_path,
        store_backend=team.spec.shared_documents.store_backend,
        embeddings=team.spec.shared_documents.embeddings,
        chunking=team.spec.shared_documents.chunking,
    )
    run_ingest(
        ingest_config,
        agent_name=team.metadata.name,
        provider=team.spec.model.provider if team.spec.model else "",
        base_dir=team_dir,
    )


def apply_shared_stores(
    role: RoleDefinition,
    team: TeamDefinition,
    shared_mem_path: str | None,
    shared_doc_path: str | None,
) -> None:
    """Patch a synthesized role with shared memory and/or shared document stores."""
    if shared_mem_path:
        from initrunner.compose.orchestrator import apply_shared_memory

        apply_shared_memory(role, shared_mem_path, team.spec.shared_memory.max_memories)

    if shared_doc_path:
        from initrunner.agent.schema.ingestion import IngestConfig

        role.spec.ingest = IngestConfig(
            sources=[],
            store_path=shared_doc_path,
            store_backend=team.spec.shared_documents.store_backend,
            embeddings=team.spec.shared_documents.embeddings,
        )


# ---------------------------------------------------------------------------
# Minimal RoleDefinition synthesis for store access (CLI inspect, etc.)
# ---------------------------------------------------------------------------


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
