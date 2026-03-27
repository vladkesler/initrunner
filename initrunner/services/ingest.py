"""Shared ingest helper for CLI and run-time auto-ingest."""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from initrunner.agent.schema.role import RoleDefinition
from initrunner.ingestion.pipeline import FileStatus, IngestStats

_logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Base-dir resolution
# ---------------------------------------------------------------------------


def effective_ingest_base_dir(role_file: Path) -> Path:
    """Return CWD for bundled starters, YAML parent for local files."""
    from initrunner.services.starters import STARTERS_DIR

    try:
        if role_file.resolve().is_relative_to(STARTERS_DIR.resolve()):
            return Path.cwd()
    except ValueError:
        pass
    return role_file.parent


# ---------------------------------------------------------------------------
# First-run detection
# ---------------------------------------------------------------------------


def is_store_populated(agent_name: str, store_path: str | None = None) -> bool:
    """Return True if the document store has indexed chunks."""
    from initrunner.stores.base import resolve_store_path

    db_path = resolve_store_path(store_path, agent_name)
    if not db_path.exists():
        return False

    try:
        import lancedb  # type: ignore[import-not-found]

        from initrunner.stores._lance_common import _table_names

        db = lancedb.connect(str(db_path))
        if "chunks" not in _table_names(db):
            return False
        tbl = db.open_table("chunks")
        return tbl.count_rows() > 0
    except Exception:
        _logger.debug("Could not check store %s", db_path, exc_info=True)
        return False


# ---------------------------------------------------------------------------
# Auto-ingest
# ---------------------------------------------------------------------------


def resolve_auto_ingest_total(
    role: RoleDefinition,
    role_file: Path,
) -> int | None:
    """Return the source count if auto-ingest will run, else ``None``.

    Checks the same preconditions as :func:`auto_ingest_if_needed` (config
    present, ``auto`` flag set, store empty) and resolves the full source set
    including managed sources to return an accurate total.
    """
    ingest = role.spec.ingest
    if ingest is None or not ingest.auto or not ingest.sources:
        return None
    if is_store_populated(role.metadata.name, ingest.store_path):
        return None

    from initrunner.ingestion.pipeline import resolve_full_sources

    base_dir = effective_ingest_base_dir(role_file)
    all_files, all_urls = resolve_full_sources(ingest, role.metadata.name, base_dir=base_dir)
    return len(all_files) + len(all_urls)


def auto_ingest_if_needed(
    role: RoleDefinition,
    role_file: Path,
    *,
    progress_callback: Callable[[Path, FileStatus], None] | None = None,
) -> IngestStats | None:
    """Run ingestion if ``ingest.auto`` is True and the store is empty.

    Returns :class:`IngestStats` if ingestion ran, ``None`` if skipped.
    Lets :class:`EmbeddingModelChangedError` propagate to the caller.
    """
    from initrunner.agent.loader import _load_dotenv
    from initrunner.ingestion.pipeline import run_ingest

    ingest = role.spec.ingest
    if ingest is None or not ingest.auto or not ingest.sources:
        return None

    if is_store_populated(role.metadata.name, ingest.store_path):
        return None

    base_dir = effective_ingest_base_dir(role_file)
    _load_dotenv(base_dir)

    resource_limits = role.spec.security.resources
    return run_ingest(
        ingest,
        role.metadata.name,
        provider=role.spec.model.provider,
        base_dir=base_dir,
        progress_callback=progress_callback,
        max_file_size_mb=resource_limits.max_file_size_mb,
        max_total_ingest_mb=resource_limits.max_total_ingest_mb,
    )
