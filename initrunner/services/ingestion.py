"""Ingestion service -- sync wrappers for dashboard and CLI consumers."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from initrunner.agent.schema.role import RoleDefinition
    from initrunner.ingestion.pipeline import FileStatus, IngestStats


@dataclass
class IngestedDocument:
    """A single ingested source with its metadata."""

    source: str
    chunk_count: int
    ingested_at: str
    content_hash: str
    last_modified: float
    is_managed: bool


@dataclass
class IngestSummaryInfo:
    """Aggregate statistics for an agent's document store."""

    total_documents: int
    total_chunks: int
    store_path: str
    sources_config: list[str]
    managed_count: int
    last_ingested_at: str | None


def _open_doc_store(role: RoleDefinition):
    """Open the agent's document store (read-only, no dimensions needed)."""
    from initrunner.stores.base import resolve_store_path
    from initrunner.stores.factory import create_document_store

    cfg = role.spec.ingest
    if cfg is None:
        return None, None
    db_path = resolve_store_path(cfg.store_path, role.metadata.name)
    if not db_path.exists():
        return None, db_path
    return create_document_store(cfg.store_backend, db_path), db_path


def list_ingested_documents_sync(role: RoleDefinition) -> list[IngestedDocument]:
    """List all ingested documents with managed-source flag."""
    from initrunner.ingestion.manifest import read_manifest

    store, _db_path = _open_doc_store(role)
    if store is None:
        return []

    with store:
        rows = store.list_all_file_metadata()
        manifest = read_manifest(store)

    managed_paths = {s.path for s in manifest}
    return [
        IngestedDocument(
            source=source,
            chunk_count=chunk_count,
            ingested_at=ingested_at,
            content_hash=content_hash,
            last_modified=last_modified,
            is_managed=source in managed_paths,
        )
        for source, content_hash, last_modified, ingested_at, chunk_count in rows
    ]


def get_ingest_summary_sync(role: RoleDefinition) -> IngestSummaryInfo:
    """Return aggregate ingest stats for the agent."""
    from initrunner.ingestion.manifest import read_manifest

    cfg = role.spec.ingest
    sources_config = cfg.sources if cfg else []

    store, db_path = _open_doc_store(role)
    if store is None:
        return IngestSummaryInfo(
            total_documents=0,
            total_chunks=0,
            store_path=str(db_path) if db_path else "",
            sources_config=sources_config,
            managed_count=0,
            last_ingested_at=None,
        )

    with store:
        rows = store.list_all_file_metadata()
        total_chunks = store.count()
        manifest = read_manifest(store)

    last_ingested = max((r[3] for r in rows), default=None) if rows else None

    return IngestSummaryInfo(
        total_documents=len(rows),
        total_chunks=total_chunks,
        store_path=str(db_path),
        sources_config=sources_config,
        managed_count=len(manifest),
        last_ingested_at=last_ingested,
    )


def delete_ingested_source_sync(role: RoleDefinition, source: str) -> int:
    """Delete a source from the store and manifest. Returns chunks deleted."""
    from initrunner.ingestion.manifest import remove_from_manifest, uploads_dir

    store, _db_path = _open_doc_store(role)
    if store is None:
        return 0

    with store:
        deleted = store.delete_by_source(source)
        store.delete_file_metadata(source)
        remove_from_manifest(store, source)

    # Clean up uploaded file if it's in the uploads directory
    try:
        upload_dir = uploads_dir(role.metadata.name)
        source_path = Path(source).resolve()
        if source_path.is_relative_to(upload_dir.resolve()) and source_path.is_file():
            source_path.unlink()
    except (ValueError, OSError):
        pass

    return deleted


def run_ingest_managed_sync(
    role: RoleDefinition,
    role_path: Path,
    *,
    files: list[Path] | None = None,
    urls: list[str] | None = None,
    progress_callback: Callable[[Path, FileStatus], None] | None = None,
) -> IngestStats | None:
    """Ingest explicit files/URLs via the managed source pipeline (sync)."""
    from initrunner.agent.loader import _load_dotenv
    from initrunner.ingestion.pipeline import run_ingest_managed

    _load_dotenv(role_path.parent)

    if role.spec.ingest is None:
        return None

    return run_ingest_managed(
        files=files or [],
        urls=urls or [],
        config=role.spec.ingest,
        agent_name=role.metadata.name,
        provider=role.spec.model.provider,  # type: ignore[union-attr]
        progress_callback=progress_callback,
    )
