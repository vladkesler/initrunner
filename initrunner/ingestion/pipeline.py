"""Ingestion pipeline: glob sources → extract → chunk → embed → store."""

from __future__ import annotations

import asyncio
import glob as globmod
import hashlib
import logging
import os
import threading
import time
from collections.abc import Callable
from contextlib import ExitStack
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from urllib.parse import urlparse

from pydantic_ai.embeddings import Embedder

from initrunner.agent.schema.ingestion import IngestConfig
from initrunner.ingestion.chunker import Chunk, chunk_text
from initrunner.ingestion.embeddings import compute_model_identity, create_embedder, embed_texts
from initrunner.ingestion.extractors import extract_text
from initrunner.stores.base import DocumentStore, StoreBackend, resolve_store_path
from initrunner.stores.factory import create_document_store

_EMBED_BATCH_SIZE = 500
_DOMAIN_DELAY_SECONDS = 1.0
_URL_FETCH_TIMEOUT = 15  # seconds

_ingest_locks: dict[str, threading.Lock] = {}
_ingest_locks_guard = threading.Lock()


def _get_ingest_lock(db_path: Path) -> threading.Lock:
    """Return a per-db-path lock for concurrent ingestion protection."""
    key = str(db_path.resolve())
    with _ingest_locks_guard:
        if key not in _ingest_locks:
            _ingest_locks[key] = threading.Lock()
        return _ingest_locks[key]


logger = logging.getLogger(__name__)


def _run_async(coro):
    """Run an async coroutine from sync context, reusing an existing loop if possible."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop is not None and loop.is_running():
        # We're inside an async context (e.g. called via asyncio.to_thread from API/TUI).
        # Create a new loop in a thread-safe way.
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, coro).result()
    return asyncio.run(coro)


def _embed_batch(
    embedder: Embedder, texts: list[str], batch_size: int = _EMBED_BATCH_SIZE
) -> list[list[float]]:
    """Embed texts in batches to limit peak memory usage."""

    async def _embed_all() -> list[list[float]]:
        if len(texts) <= batch_size:
            return await embed_texts(embedder, texts)
        all_embeddings: list[list[float]] = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            all_embeddings.extend(await embed_texts(embedder, batch))
        return all_embeddings

    return _run_async(_embed_all())


class FileStatus(StrEnum):
    NEW = "new"
    UPDATED = "updated"
    SKIPPED = "skipped"
    ERROR = "error"


@dataclass
class FileResult:
    path: Path
    status: FileStatus
    chunks: int = 0
    error: str | None = None


@dataclass
class IngestStats:
    new: int = 0
    updated: int = 0
    skipped: int = 0
    errored: int = 0
    total_chunks: int = 0
    file_results: list[FileResult] = field(default_factory=list)


def _is_url(source: str) -> bool:
    """Return True if *source* looks like an HTTP(S) URL."""
    return source.startswith("http://") or source.startswith("https://")


def _resolve_file_sources(sources: list[str], base_dir: Path | None = None) -> list[Path]:
    """Expand glob patterns into concrete file paths."""
    files: list[Path] = []
    for pattern in sources:
        if base_dir:
            pattern = str(base_dir / pattern)
        matches = globmod.glob(pattern, recursive=True)
        files.extend(Path(m) for m in matches if Path(m).is_file())
    return sorted(set(files))


def resolve_sources(
    sources: list[str], base_dir: Path | None = None
) -> tuple[list[Path], list[str]]:
    """Expand sources into (file_paths, urls)."""
    globs = [s for s in sources if not _is_url(s)]
    urls = [s for s in sources if _is_url(s)]
    files = _resolve_file_sources(globs, base_dir)
    return files, urls


def _file_hash(path: Path) -> str:
    """SHA-256 hex digest of file bytes."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            block = f.read(8192)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def _content_hash(text: str) -> str:
    """SHA-256 hex digest of text content."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _get_store_path(agent_name: str, store_path: str | None) -> Path:
    return resolve_store_path(store_path, agent_name)


def _record_error(
    stats: IngestStats,
    source: Path | str,
    error_msg: str,
    progress_callback: Callable[[Path, FileStatus], None] | None,
) -> FileResult:
    """Record an error for a source (Path or URL string) in stats."""
    path = source if isinstance(source, Path) else Path(source)
    result = FileResult(path=path, status=FileStatus.ERROR, error=error_msg)
    stats.file_results.append(result)
    stats.errored += 1
    if progress_callback:
        progress_callback(path, FileStatus.ERROR)
    return result


def _read_file_hashes(
    backend: StoreBackend,
    db_path: Path,
) -> dict[str, str]:
    """Read {source: content_hash} via the store abstraction.

    Returns an empty dict for new databases (no existing store).
    """
    if not db_path.exists():
        return {}
    with create_document_store(backend, db_path) as store:
        return store.list_file_hashes()


def _check_cached_hash(
    source_key: str,
    content_hash: str,
    file_metadata: dict[str, str],
    *,
    force: bool,
    display_path: Path,
    stats: IngestStats,
    progress_callback: Callable[[Path, FileStatus], None] | None,
) -> FileStatus | None:
    """Compare *content_hash* against cached metadata for *source_key*.

    Returns ``None`` if the source was skipped (already recorded in *stats*),
    or the appropriate ``FileStatus`` (NEW / UPDATED) if it should be processed.
    If *force* is ``True``, always returns ``FileStatus.NEW``.
    """
    if force:
        return FileStatus.NEW

    cached_hash = file_metadata.get(source_key)
    if cached_hash is not None and cached_hash == content_hash:
        result = FileResult(path=display_path, status=FileStatus.SKIPPED)
        stats.file_results.append(result)
        stats.skipped += 1
        if progress_callback:
            progress_callback(display_path, FileStatus.SKIPPED)
        return None

    return FileStatus.UPDATED if cached_hash is not None else FileStatus.NEW


def _classify_files(
    files: list[Path],
    file_metadata: dict[str, str],
    stats: IngestStats,
    *,
    force: bool,
    max_file_size_mb: float,
    max_total_ingest_mb: float,
    progress_callback: Callable[[Path, FileStatus], None] | None,
) -> tuple[list[tuple[Path, FileStatus]], set[str]]:
    """Classify files as NEW, UPDATED, SKIPPED, or ERROR.

    Returns (to_process, resolved_sources).
    """
    to_process: list[tuple[Path, FileStatus]] = []
    resolved_sources: set[str] = set()

    cumulative_bytes = 0
    max_file_bytes = int(max_file_size_mb * 1024 * 1024) if max_file_size_mb > 0 else 0
    max_total_bytes = int(max_total_ingest_mb * 1024 * 1024) if max_total_ingest_mb > 0 else 0

    for f in files:
        source = str(f)
        resolved_sources.add(source)

        # Resource limits check
        if max_file_bytes > 0 or max_total_bytes > 0:
            try:
                file_size = f.stat().st_size
            except OSError as e:
                _record_error(stats, f, str(e), progress_callback)
                continue

            if max_file_bytes > 0 and file_size > max_file_bytes:
                _record_error(
                    stats,
                    f,
                    f"File size ({file_size / 1024 / 1024:.1f} MB) exceeds limit "
                    f"({max_file_size_mb} MB)",
                    progress_callback,
                )
                continue

            if max_total_bytes > 0 and cumulative_bytes + file_size > max_total_bytes:
                _record_error(
                    stats,
                    f,
                    f"Total ingest size would exceed limit ({max_total_ingest_mb} MB)",
                    progress_callback,
                )
                continue

            cumulative_bytes += file_size

        if not force:
            try:
                content_hash = _file_hash(f)
            except OSError as e:
                _record_error(stats, f, str(e), progress_callback)
                continue
        else:
            content_hash = ""

        status = _check_cached_hash(
            source,
            content_hash,
            file_metadata,
            force=force,
            display_path=f,
            stats=stats,
            progress_callback=progress_callback,
        )
        if status is None:
            continue

        to_process.append((f, status))

    return to_process, resolved_sources


def _classify_urls(
    urls: list[str],
    file_metadata: dict[str, str],
    stats: IngestStats,
    *,
    force: bool,
    progress_callback: Callable[[Path, FileStatus], None] | None,
) -> tuple[list[tuple[str, FileStatus, str]], set[str]]:
    """Classify URLs as NEW, UPDATED, SKIPPED, or ERROR.

    Fetches each URL, computes content hash on the extracted markdown, and
    compares against the stored hash for incremental skip.

    Returns (to_process, resolved_url_sources) where each to_process entry
    is (url, status, extracted_markdown_text).
    """
    from initrunner.ingestion.extractors import extract_url

    to_process: list[tuple[str, FileStatus, str]] = []
    resolved_sources: set[str] = set()
    domain_last_request: dict[str, float] = {}

    for url in urls:
        resolved_sources.add(url)

        # Per-domain rate limiting
        domain = urlparse(url).hostname or ""
        last = domain_last_request.get(domain)
        if last is not None:
            elapsed = time.monotonic() - last
            if elapsed < _DOMAIN_DELAY_SECONDS:
                time.sleep(_DOMAIN_DELAY_SECONDS - elapsed)

        try:
            text = extract_url(url, timeout=_URL_FETCH_TIMEOUT)
        except Exception as e:
            logger.warning("Failed to fetch URL %s: %s", url, e)
            _record_error(stats, url, f"Fetch error: {e}", progress_callback)
            domain_last_request[domain] = time.monotonic()
            continue

        domain_last_request[domain] = time.monotonic()

        url_hash = _content_hash(text) if not force else ""
        status = _check_cached_hash(
            url,
            url_hash,
            file_metadata,
            force=force,
            display_path=Path(url),
            stats=stats,
            progress_callback=progress_callback,
        )
        if status is None:
            continue

        to_process.append((url, status, text))

    return to_process, resolved_sources


def _chunk_urls(
    to_process: list[tuple[str, FileStatus, str]],
    config: IngestConfig,
    stats: IngestStats,
    progress_callback: Callable[[Path, FileStatus], None] | None,
) -> list[tuple[str, FileStatus, str, list[Chunk]]]:
    """Chunk pre-fetched URL text. Returns list of (url, status, text, chunks)."""
    url_chunks: list[tuple[str, FileStatus, str, list[Chunk]]] = []
    for url, status, text in to_process:
        chunks = chunk_text(
            text,
            source=url,
            strategy=config.chunking.strategy,
            chunk_size=config.chunking.chunk_size,
            chunk_overlap=config.chunking.chunk_overlap,
        )
        if not chunks:
            _record_error(stats, url, "No chunks extracted", progress_callback)
            continue

        url_chunks.append((url, status, text, chunks))
    return url_chunks


def _extract_and_chunk(
    to_process: list[tuple[Path, FileStatus]],
    config: IngestConfig,
    stats: IngestStats,
    progress_callback: Callable[[Path, FileStatus], None] | None,
) -> list[tuple[Path, FileStatus, list[Chunk]]]:
    """Extract text and chunk each file. Returns list of (path, status, chunks)."""
    file_chunks: list[tuple[Path, FileStatus, list[Chunk]]] = []
    for f, status in to_process:
        try:
            text = extract_text(f)
        except (ValueError, OSError) as e:
            _record_error(stats, f, str(e), progress_callback)
            continue

        chunks = chunk_text(
            text,
            source=str(f),
            strategy=config.chunking.strategy,
            chunk_size=config.chunking.chunk_size,
            chunk_overlap=config.chunking.chunk_overlap,
        )
        if not chunks:
            _record_error(stats, f, "No chunks extracted", progress_callback)
            continue

        file_chunks.append((f, status, chunks))
    return file_chunks


class _SourceItem:
    """Pre-processed item ready for embed-and-store."""

    __slots__ = ("chunks", "content_hash", "display_path", "last_modified", "source_id", "status")

    def __init__(
        self,
        source_id: str,
        display_path: Path,
        status: FileStatus,
        chunks: list[Chunk],
        content_hash: str,
        last_modified: float,
    ) -> None:
        self.source_id = source_id
        self.display_path = display_path
        self.status = status
        self.chunks = chunks
        self.content_hash = content_hash
        self.last_modified = last_modified


def _embed_and_store_items(
    items: list[_SourceItem],
    embedder: Embedder,
    config: IngestConfig,
    db_path: Path,
    now: str,
    stats: IngestStats,
    progress_callback: Callable[[Path, FileStatus], None] | None,
    error_fn: Callable[
        [IngestStats, str | Path, str, Callable[[Path, FileStatus], None] | None],
        FileResult | None,
    ],
    *,
    existing_store: DocumentStore | None = None,
    stack: ExitStack | None = None,
) -> DocumentStore | None:
    """Embed items in batches, store results. Returns the opened store."""
    store = existing_store

    own_stack = stack is None
    if own_stack:
        stack = ExitStack()
    assert stack is not None

    try:
        for item in items:
            chunk_texts = [c.text for c in item.chunks]

            chunk_embeddings = _embed_batch(embedder, chunk_texts)
            if not chunk_embeddings:
                error_fn(stats, item.source_id, "Embedding returned empty", progress_callback)
                continue

            # Open store lazily once we know dimensions
            if store is None:
                dimensions = len(chunk_embeddings[0])
                store = stack.enter_context(
                    create_document_store(config.store_backend, db_path, dimensions=dimensions)
                )

            chunk_count = len(item.chunks)

            store.replace_source(
                source=item.source_id,
                texts=chunk_texts,
                embeddings=chunk_embeddings,
                ingested_at=now,
                content_hash=item.content_hash,
                last_modified=item.last_modified,
            )

            result = FileResult(path=item.display_path, status=item.status, chunks=chunk_count)
            stats.file_results.append(result)
            stats.total_chunks += chunk_count

            if item.status == FileStatus.NEW:
                stats.new += 1
            elif item.status == FileStatus.UPDATED:
                stats.updated += 1

            if progress_callback:
                progress_callback(item.display_path, item.status)
    finally:
        if own_stack:
            stack.close()

    return store


def _embed_and_store(
    file_chunks: list[tuple[Path, FileStatus, list[Chunk]]],
    embedder: Embedder,
    config: IngestConfig,
    db_path: Path,
    now: str,
    stats: IngestStats,
    resolved_sources: set[str],
    progress_callback: Callable[[Path, FileStatus], None] | None,
    *,
    existing_store: DocumentStore | None = None,
    stack: ExitStack | None = None,
) -> DocumentStore | None:
    """Embed per-file in batches, store results, and purge deleted sources.

    Returns the opened store (or *existing_store*) so URL pipeline can reuse it.
    """
    items: list[_SourceItem] = []
    for f, status, chunks in file_chunks:
        try:
            content_hash = _file_hash(f)
            last_modified = os.stat(f).st_mtime
        except OSError as e:
            _record_error(stats, f, str(e), progress_callback)
            continue
        items.append(_SourceItem(str(f), f, status, chunks, content_hash, last_modified))

    store = _embed_and_store_items(
        items,
        embedder,
        config,
        db_path,
        now,
        stats,
        progress_callback,
        _record_error,
        existing_store=existing_store,
        stack=stack,
    )

    # Purge deleted files (only file sources — URL sources are never auto-purged)
    if store is not None:
        _purge_deleted(store, resolved_sources)

    return store


def _embed_and_store_urls(
    url_chunks: list[tuple[str, FileStatus, str, list[Chunk]]],
    embedder: Embedder,
    config: IngestConfig,
    db_path: Path,
    now: str,
    stats: IngestStats,
    progress_callback: Callable[[Path, FileStatus], None] | None,
    *,
    existing_store: DocumentStore | None = None,
    stack: ExitStack | None = None,
) -> DocumentStore | None:
    """Embed and store URL-sourced chunks. Returns the store."""
    items: list[_SourceItem] = []
    for url, status, text, chunks in url_chunks:
        items.append(_SourceItem(url, Path(url), status, chunks, _content_hash(text), time.time()))

    return _embed_and_store_items(
        items,
        embedder,
        config,
        db_path,
        now,
        stats,
        progress_callback,
        _record_error,
        existing_store=existing_store,
        stack=stack,
    )


def run_ingest(
    config: IngestConfig,
    agent_name: str,
    provider: str = "openai",
    *,
    base_dir: Path | None = None,
    force: bool = False,
    progress_callback: Callable[[Path, FileStatus], None] | None = None,
    max_file_size_mb: float = 0,
    max_total_ingest_mb: float = 0,
) -> IngestStats:
    """Run the full ingestion pipeline synchronously. Returns IngestStats."""
    from opentelemetry import trace

    tracer = trace.get_tracer("initrunner")

    stats = IngestStats()
    files, urls = resolve_sources(config.sources, base_dir=base_dir)
    if not files and not urls:
        return stats

    db_path = _get_store_path(agent_name, config.store_path)

    ingest_span = tracer.start_span(
        "initrunner.ingest",
        attributes={"initrunner.agent_name": agent_name},
    )

    lock = _get_ingest_lock(db_path)
    if not lock.acquire(blocking=False):
        raise RuntimeError(f"Ingestion already in progress for {db_path}")

    try:
        # Embed setup
        embed_provider = config.embeddings.provider or provider
        embedder = create_embedder(
            embed_provider,
            config.embeddings.model,
            base_url=config.embeddings.base_url,
            api_key_env=config.embeddings.api_key_env,
        )

        # --- Model change detection ---
        current_identity = compute_model_identity(
            embed_provider, config.embeddings.model, config.embeddings.base_url
        )
        if db_path.exists():
            from initrunner.stores.sqlite_vec import (
                EmbeddingModelChangedError,
                _open_sqlite_vec,
                _read_meta,
                _write_meta,
                wipe_document_store,
            )

            check_conn = _open_sqlite_vec(db_path)
            try:
                stored_identity = _read_meta(check_conn, "embedding_model")
            finally:
                check_conn.close()

            if stored_identity is None:
                # Legacy store — record current identity, don't wipe
                logging.getLogger(__name__).warning(
                    "No embedding model recorded in store. "
                    "Recording '%s' for future change detection.",
                    current_identity,
                )
                rec_conn = _open_sqlite_vec(db_path)
                try:
                    _write_meta(rec_conn, "embedding_model", current_identity)
                finally:
                    rec_conn.close()
            elif stored_identity != current_identity:
                if force:
                    logging.getLogger(__name__).warning(
                        "Embedding model changed from %s to %s. "
                        "Wiping store and re-ingesting all documents.",
                        stored_identity,
                        current_identity,
                    )
                    wipe_document_store(db_path)
                else:
                    raise EmbeddingModelChangedError(
                        f"Embedding model changed from {stored_identity} to {current_identity}. "
                        "Run with --force to wipe the store and re-ingest."
                    )

        now = datetime.now(UTC).isoformat()

        file_metadata = _read_file_hashes(config.store_backend, db_path)

        # --- File pipeline ---
        file_resolved_sources: set[str] = set()
        with ExitStack() as stack:
            store: DocumentStore | None = None

            if files:
                to_process, file_resolved_sources = _classify_files(
                    files,
                    file_metadata,
                    stats,
                    force=force,
                    max_file_size_mb=max_file_size_mb,
                    max_total_ingest_mb=max_total_ingest_mb,
                    progress_callback=progress_callback,
                )

                file_chunks = _extract_and_chunk(to_process, config, stats, progress_callback)

                if file_chunks:
                    store = _embed_and_store(
                        file_chunks,
                        embedder,
                        config,
                        db_path,
                        now,
                        stats,
                        file_resolved_sources,
                        progress_callback,
                        stack=stack,
                    )
                elif not to_process and file_resolved_sources:
                    # All skipped/errored — still need to purge deleted files
                    if db_path.exists():
                        store = stack.enter_context(
                            create_document_store(config.store_backend, db_path)
                        )
                        _purge_deleted(store, file_resolved_sources)

            # --- URL pipeline ---
            if urls:
                url_to_process, _url_resolved = _classify_urls(
                    urls, file_metadata, stats, force=force, progress_callback=progress_callback
                )

                if url_to_process:
                    url_chunked = _chunk_urls(url_to_process, config, stats, progress_callback)
                    if url_chunked:
                        store = _embed_and_store_urls(
                            url_chunked,
                            embedder,
                            config,
                            db_path,
                            now,
                            stats,
                            progress_callback,
                            existing_store=store,
                            stack=stack,
                        )

            # Record the embedding model identity after successful ingestion
            if db_path.exists() and (stats.new or stats.updated or force):
                from initrunner.stores.sqlite_vec import (
                    _open_sqlite_vec,
                    _write_meta,
                )

                write_conn = _open_sqlite_vec(db_path)
                try:
                    _write_meta(write_conn, "embedding_model", current_identity)
                finally:
                    write_conn.close()
    finally:
        lock.release()

    ingest_span.set_attribute("initrunner.ingest.files_processed", stats.new + stats.updated)
    ingest_span.set_attribute("initrunner.ingest.chunks_created", stats.total_chunks)
    ingest_span.end()

    return stats


def _purge_deleted(store: DocumentStore, resolved_sources: set[str]) -> None:
    """Remove chunks and metadata for file sources no longer on disk.

    URL sources are never auto-purged — remove them from the config to stop
    re-ingesting, but stored content persists until manually cleared.
    """
    known_sources = store.list_sources()
    for source in known_sources:
        # Skip URL sources from purging
        if _is_url(source):
            continue
        if source not in resolved_sources:
            store.delete_by_source(source)
            store.delete_file_metadata(source)
