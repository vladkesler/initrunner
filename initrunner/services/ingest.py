"""Shared ingest helper for CLI and run-time auto-ingest."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from initrunner.agent.schema.role import RoleDefinition
from initrunner.ingestion.pipeline import FileStatus, IngestStats, _file_hash

# `_file_hash` is imported at module level (instead of inside
# `compute_stale_ingest_plan`) so tests can monkeypatch it via
# `initrunner.services.ingest._file_hash` to assert the mtime fast-path.

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
# Auto-ingest planning
# ---------------------------------------------------------------------------


@dataclass
class IngestPlan:
    """Cheap pre-flight summary: existence implies the pipeline should run.

    ``progress_total`` is the count of items the pipeline will iterate (which
    can legitimately be 0 for a purge-only or legacy-store identity-record
    run). The CLI helper hides the progress bar when this is 0.
    """

    progress_total: int


def compute_stale_ingest_plan(
    role: RoleDefinition,
    role_file: Path,
) -> IngestPlan | None:
    """Cheap stale check. Returns None if auto-ingest doesn't apply or no
    work is needed; returns an :class:`IngestPlan` otherwise.

    Cheap by design: uses an mtime fast-path so unchanged files are NOT
    hashed. URLs are NEVER fetched here. Also detects embedding-model
    identity changes (and legacy stores with no recorded identity) in the
    same store-read.

    Tolerant: any read failure on the store metadata falls back to "treat
    as fresh" so the pipeline does the authoritative work under its own
    lock. Lock-free reads are safe -- LanceDB handles concurrent readers;
    the per-db ingest lock only guards writes inside ``_execute_ingest_core``.
    """
    from initrunner.ingestion.embeddings import compute_model_identity
    from initrunner.ingestion.pipeline import _is_url, resolve_full_sources
    from initrunner.stores.base import resolve_store_path
    from initrunner.stores.factory import create_document_store

    ingest = role.spec.ingest
    if ingest is None or not ingest.auto:
        return None
    # Deliberately do NOT gate on `not ingest.sources`: a role with
    # ``sources: []`` plus manifest-managed dashboard uploads is a real case
    # that ``resolve_full_sources`` already handles.

    base_dir = effective_ingest_base_dir(role_file)
    files, urls = resolve_full_sources(ingest, role.metadata.name, base_dir=base_dir)
    current_file_keys = {str(f) for f in files}

    db_path = resolve_store_path(ingest.store_path, role.metadata.name)
    if not db_path.exists():
        # Empty store: every file/URL is new.
        if not files and not urls:
            return None
        return IngestPlan(progress_total=len(files) + len(urls))

    try:
        with create_document_store(ingest.store_backend, db_path) as store:
            rows = store.list_all_file_metadata()
            stored_identity = store.read_store_meta("embedding_model")
    except Exception:
        _logger.debug(
            "Could not read store metadata at %s; deferring to pipeline",
            db_path,
            exc_info=True,
        )
        if not files and not urls:
            return None
        return IngestPlan(progress_total=len(files) + len(urls))

    # rows: list[(source, content_hash, last_modified, ingested_at, chunk_count)]
    indexed: dict[str, tuple[str, float]] = {row[0]: (row[1], row[2]) for row in rows}

    # Embedding-model identity check: detect a model swap with no file
    # changes. ALSO treat "rows exist but no recorded identity" as a reason
    # to invoke the pipeline -- this is a legacy store from before identity
    # tracking; the run will trigger ``_setup_embedder_and_check_model`` to
    # record the current identity for future change detection.
    embed_provider = ingest.embeddings.provider or role.spec.model.provider  # type: ignore[union-attr]
    current_identity = compute_model_identity(
        embed_provider, ingest.embeddings.model, ingest.embeddings.base_url
    )
    needs_identity_record_or_update = bool(rows) and (
        stored_identity is None or stored_identity != current_identity
    )

    new_or_updated_files = 0
    for f in files:
        key = str(f)
        prior = indexed.get(key)
        if prior is None:
            new_or_updated_files += 1
            continue

        prior_hash, prior_mtime = prior
        try:
            current_mtime = f.stat().st_mtime
        except OSError:
            new_or_updated_files += 1  # let the pipeline surface the error
            continue

        # Mtime fast-path: when the stored mtime matches, we ASSUME the
        # content is unchanged and skip hashing. This is a heuristic, not a
        # proof: tools that preserve timestamps (cp -p, rsync -a, tar -p)
        # can defeat it. Users who care should run
        # ``initrunner ingest <role> --force`` for an authoritative rebuild.
        if current_mtime == prior_mtime:
            continue

        # Mtime moved: confirm with a hash before declaring an update.
        try:
            current_hash = _file_hash(f)
        except OSError:
            new_or_updated_files += 1
            continue
        if current_hash != prior_hash:
            new_or_updated_files += 1

    # Removed files: file-type sources in the store but no longer matched.
    indexed_file_keys = {k for k in indexed if not _is_url(k)}
    removed_files = len(indexed_file_keys - current_file_keys)

    # New URLs: in YAML but not yet indexed. Existing URLs are not refetched
    # (auto mode passes ``skip_existing_urls=True`` to ``run_ingest``).
    indexed_url_keys = set(indexed) - indexed_file_keys
    new_urls = sum(1 for u in urls if u not in indexed_url_keys)

    has_work = new_or_updated_files or removed_files or new_urls or needs_identity_record_or_update
    if not has_work:
        return None

    # progress_total is the bar total. The pipeline iterates every file in
    # resolved sources (skipped files still tick the bar), so use the full
    # source count for an honest "X of Y" display. For purge-only and
    # legacy-identity-record runs this can legitimately be 0; the helper
    # hides the progress bar in that case.
    return IngestPlan(progress_total=len(files) + len(urls))


def run_auto_ingest(
    role: RoleDefinition,
    role_file: Path,
    *,
    progress_callback: Callable[[Path, FileStatus], None] | None = None,
) -> IngestStats:
    """Run the ingestion pipeline for an auto-ingest hit.

    Caller must have already confirmed :func:`compute_stale_ingest_plan`
    returned a non-None plan. Sets ``skip_existing_urls=True`` to suppress
    per-run network calls. Lets :class:`EmbeddingModelChangedError` propagate
    so the CLI helper can show the ``--force`` hint.
    """
    from initrunner.agent.loader import _load_dotenv
    from initrunner.ingestion.pipeline import run_ingest

    ingest = role.spec.ingest
    assert ingest is not None  # plan would be None otherwise
    base_dir = effective_ingest_base_dir(role_file)
    _load_dotenv(base_dir)

    resource_limits = role.spec.security.resources
    return run_ingest(
        ingest,
        role.metadata.name,
        provider=role.spec.model.provider,  # type: ignore[union-attr]
        base_dir=base_dir,
        progress_callback=progress_callback,
        max_file_size_mb=resource_limits.max_file_size_mb,
        max_total_ingest_mb=resource_limits.max_total_ingest_mb,
        skip_existing_urls=True,
    )
