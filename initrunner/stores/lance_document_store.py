"""LanceDB-backed DocumentStore implementation."""

from __future__ import annotations

import fnmatch
import shutil
import threading
from pathlib import Path

import lancedb  # type: ignore[import-not-found]
import pyarrow as pa  # type: ignore[import-not-found]

from initrunner._paths import ensure_private_dir
from initrunner.stores._helpers import _glob_to_sql_like
from initrunner.stores._lance_common import (
    _ensure_meta_table,
    _esc,
    _open_db,
    _read_meta,
    _resolve_dimensions,
    _safe_id,
    _table_names,
    _write_meta,
)
from initrunner.stores.base import DocumentStore, SearchResult

# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

_FILE_META_SCHEMA = pa.schema(
    [
        pa.field("id", pa.string()),
        pa.field("source", pa.string()),
        pa.field("content_hash", pa.string()),
        pa.field("last_modified", pa.float64()),
        pa.field("ingested_at", pa.string()),
        pa.field("chunk_count", pa.int32()),
    ]
)


def _make_chunks_schema(dimensions: int) -> pa.Schema:
    return pa.schema(
        [
            pa.field("id", pa.int64()),
            pa.field("text", pa.large_string()),
            pa.field("source", pa.string()),
            pa.field("chunk_index", pa.int32()),
            pa.field("ingested_at", pa.string()),
            pa.field("vector", pa.list_(pa.float32(), dimensions)),
        ]
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def wipe_document_store(db_path: Path) -> None:
    """Remove all data from a document store by deleting the directory."""
    if db_path.exists():
        shutil.rmtree(db_path)


# ---------------------------------------------------------------------------
# LanceDocumentStore
# ---------------------------------------------------------------------------


class LanceDocumentStore(DocumentStore):
    """Vector store for ingested documents, backed by LanceDB."""

    def __init__(self, db_path: Path, dimensions: int | None = None) -> None:
        self._base_path = db_path
        self._lock = threading.Lock()

        ensure_private_dir(db_path)

        self._db: lancedb.DBConnection = _open_db(db_path)
        _ensure_meta_table(self._db)
        self._dimensions = _resolve_dimensions(self._db, db_path, dimensions)

        # File metadata table
        if "file_metadata" not in _table_names(self._db):
            self._db.create_table("file_metadata", schema=_FILE_META_SCHEMA)

        # Chunks table -- only created once dimensions are known
        self._chunks_ready = False
        if self._dimensions is not None:
            self._ensure_chunks_table(self._dimensions)

        # Auto-increment counter for chunk IDs
        raw_next = _read_meta(self._db, "next_chunk_id")
        self._next_chunk_id = int(raw_next) if raw_next is not None else 1

    def _ensure_chunks_table(self, dimensions: int) -> None:
        if "chunks" not in _table_names(self._db):
            self._db.create_table("chunks", schema=_make_chunks_schema(dimensions))
        self._chunks_ready = True

    def _alloc_ids(self, count: int) -> list[int]:
        """Allocate *count* sequential IDs."""
        start = self._next_chunk_id
        self._next_chunk_id += count
        return list(range(start, start + count))

    def _flush_counter(self) -> None:
        _write_meta(self._db, "next_chunk_id", str(self._next_chunk_id))

    @property
    def dimensions(self) -> int | None:
        return self._dimensions

    def add_documents(
        self,
        texts: list[str],
        embeddings: list[list[float]],
        sources: list[str],
        ingested_at: str = "",
    ) -> None:
        with self._lock:
            if not self._chunks_ready:
                if not embeddings:
                    return
                self._dimensions = len(embeddings[0])
                _write_meta(self._db, "dimensions", str(self._dimensions))
                self._ensure_chunks_table(self._dimensions)

            ids = self._alloc_ids(len(texts))
            data = [
                {
                    "id": doc_id,
                    "text": text,
                    "source": source,
                    "chunk_index": i,
                    "ingested_at": ingested_at,
                    "vector": emb,
                }
                for i, (doc_id, text, emb, source) in enumerate(
                    zip(ids, texts, embeddings, sources, strict=True)
                )
            ]
            tbl = self._db.open_table("chunks")
            tbl.add(data)
            self._flush_counter()

    def query(
        self,
        embedding: list[float],
        top_k: int = 5,
        source_filter: str | None = None,
    ) -> list[SearchResult]:
        with self._lock:
            if not self._chunks_ready:
                return []

            tbl = self._db.open_table("chunks")
            if tbl.count_rows() == 0:
                return []

            filter_expr: str | None = None
            use_fnmatch = False

            if source_filter is not None:
                is_glob = "*" in source_filter or "?" in source_filter

                if not is_glob:
                    filter_expr = f"source = '{_esc(source_filter)}'"
                elif "[" not in source_filter:
                    like_pattern = _glob_to_sql_like(source_filter)
                    filter_expr = f"source like '{_esc(like_pattern)}'"
                else:
                    use_fnmatch = True

            fetch_k = top_k * 10 if use_fnmatch else top_k

            q = tbl.search(embedding).metric("cosine").limit(fetch_k)  # type: ignore[unresolved-attribute]
            if filter_expr is not None:
                q = q.where(filter_expr, prefilter=True)

            results = q.select(["id", "text", "source"]).to_list()

            search_results: list[SearchResult] = []
            for row in results:
                source = row.get("source", "")
                if use_fnmatch and not fnmatch.fnmatch(source, source_filter):  # type: ignore[arg-type]
                    continue
                search_results.append(
                    SearchResult(
                        chunk_id=int(row["id"]),
                        text=row.get("text", ""),
                        source=source,
                        distance=float(row.get("_distance", 0.0)),
                    )
                )
                if len(search_results) >= top_k:
                    break

            return search_results

    def count(self) -> int:
        with self._lock:
            if not self._chunks_ready:
                return 0
            tbl = self._db.open_table("chunks")
            return tbl.count_rows()

    def delete_by_source(self, source: str) -> int:
        with self._lock:
            if not self._chunks_ready:
                return 0
            tbl = self._db.open_table("chunks")
            pred = f"source = '{_esc(source)}'"
            n = tbl.count_rows(pred)
            if n == 0:
                return 0
            tbl.delete(pred)
            return n

    # --- File metadata methods ---

    def get_file_metadata(self, source: str) -> tuple[str, float, str] | None:
        with self._lock:
            tbl = self._db.open_table("file_metadata")
            sid = _safe_id(source)
            rows = (
                tbl.search()
                .where(f"id = '{_esc(sid)}'", prefilter=True)
                .limit(1)
                .select(["content_hash", "last_modified", "ingested_at"])
                .to_list()
            )
            if not rows:
                return None
            row = rows[0]
            return (row["content_hash"], row["last_modified"], row["ingested_at"])

    def upsert_file_metadata(
        self,
        source: str,
        content_hash: str,
        last_modified: float,
        ingested_at: str,
        chunk_count: int,
    ) -> None:
        with self._lock:
            tbl = self._db.open_table("file_metadata")
            tbl.merge_insert("id").when_matched_update_all().when_not_matched_insert_all().execute(
                [
                    {
                        "id": _safe_id(source),
                        "source": source,
                        "content_hash": content_hash,
                        "last_modified": last_modified,
                        "ingested_at": ingested_at,
                        "chunk_count": chunk_count,
                    }
                ]
            )

    def delete_file_metadata(self, source: str) -> None:
        with self._lock:
            tbl = self._db.open_table("file_metadata")
            tbl.delete(f"id = '{_esc(_safe_id(source))}'")

    def list_sources(self) -> list[str]:
        with self._lock:
            tbl = self._db.open_table("file_metadata")
            if tbl.count_rows() == 0:
                return []
            arrow_tbl = tbl.to_arrow().select(["source"])
            return arrow_tbl.column("source").to_pylist()

    def list_file_hashes(self) -> dict[str, str]:
        with self._lock:
            tbl = self._db.open_table("file_metadata")
            if tbl.count_rows() == 0:
                return {}
            arrow_tbl = tbl.to_arrow().select(["source", "content_hash"])
            sources = arrow_tbl.column("source").to_pylist()
            hashes = arrow_tbl.column("content_hash").to_pylist()
            return dict(zip(sources, hashes, strict=True))

    def replace_source(
        self,
        source: str,
        texts: list[str],
        embeddings: list[list[float]],
        ingested_at: str,
        content_hash: str,
        last_modified: float,
    ) -> int:
        with self._lock:
            if self._chunks_ready:
                tbl = self._db.open_table("chunks")
                tbl.delete(f"source = '{_esc(source)}'")

                ids = self._alloc_ids(len(texts))
                data = [
                    {
                        "id": doc_id,
                        "text": text,
                        "source": source,
                        "chunk_index": i,
                        "ingested_at": ingested_at,
                        "vector": emb,
                    }
                    for i, (doc_id, text, emb) in enumerate(
                        zip(ids, texts, embeddings, strict=True)
                    )
                ]
                tbl.add(data)
                self._flush_counter()

            fm = self._db.open_table("file_metadata")
            fm.merge_insert("id").when_matched_update_all().when_not_matched_insert_all().execute(
                [
                    {
                        "id": _safe_id(source),
                        "source": source,
                        "content_hash": content_hash,
                        "last_modified": last_modified,
                        "ingested_at": ingested_at,
                        "chunk_count": len(texts),
                    }
                ]
            )
            return len(texts)

    def read_store_meta(self, key: str) -> str | None:
        with self._lock:
            return _read_meta(self._db, key)

    def write_store_meta(self, key: str, value: str) -> None:
        with self._lock:
            _write_meta(self._db, key, value)

    def close(self) -> None:
        with self._lock:
            self._flush_counter()
            self._db = None  # type: ignore[assignment]
