"""Zvec-backed DocumentStore implementation."""

from __future__ import annotations

import fnmatch
import gc
import shutil
import threading
from pathlib import Path

import zvec

from initrunner._paths import ensure_private_dir
from initrunner.stores._helpers import _glob_to_sql_like
from initrunner.stores._zvec_common import (
    _DUMMY_VEC,
    _DUMMY_VEC_VAL,
    _esc,
    _open_or_create_meta,
    _read_meta,
    _release_collection,
    _resolve_dimensions,
    _safe_id,
    _write_meta,
    _zvec_init_once,
)
from initrunner.stores.base import DocumentStore, SearchResult

# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

_FILE_META_SCHEMA = zvec.CollectionSchema(
    name="file_metadata",
    fields=[
        zvec.FieldSchema(name="source", data_type=zvec.DataType.STRING),
        zvec.FieldSchema(name="content_hash", data_type=zvec.DataType.STRING),
        zvec.FieldSchema(name="last_modified", data_type=zvec.DataType.DOUBLE),
        zvec.FieldSchema(name="ingested_at", data_type=zvec.DataType.STRING),
        zvec.FieldSchema(name="chunk_count", data_type=zvec.DataType.INT32),
    ],
    vectors=[_DUMMY_VEC],
)


def _make_chunks_schema(dimensions: int) -> zvec.CollectionSchema:
    return zvec.CollectionSchema(
        name="chunks",
        fields=[
            zvec.FieldSchema(name="text", data_type=zvec.DataType.STRING),
            zvec.FieldSchema(
                name="source",
                data_type=zvec.DataType.STRING,
                index_param=zvec.InvertIndexParam(),
            ),
            zvec.FieldSchema(name="chunk_index", data_type=zvec.DataType.INT32),
            zvec.FieldSchema(name="ingested_at", data_type=zvec.DataType.STRING),
        ],
        vectors=[
            zvec.VectorSchema(
                name="embedding",
                data_type=zvec.DataType.VECTOR_FP32,
                dimension=dimensions,
                index_param=zvec.HnswIndexParam(metric_type=zvec.MetricType.COSINE),
            ),
        ],
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def wipe_document_store(db_path: Path) -> None:
    """Remove all data from a document store by deleting and recreating the directory."""
    if db_path.exists():
        shutil.rmtree(db_path)


# ---------------------------------------------------------------------------
# ZvecDocumentStore
# ---------------------------------------------------------------------------


class ZvecDocumentStore(DocumentStore):
    """Vector store for ingested documents, backed by zvec."""

    @property
    def meta_col(self) -> zvec.Collection:
        """Return meta collection, raising if closed."""
        if self._meta_col is None:
            raise RuntimeError("ZvecDocumentStore is closed (meta collection released)")
        return self._meta_col

    @property
    def chunks_col(self) -> zvec.Collection:
        """Return chunks collection, raising if not initialized."""
        if self._chunks_col is None:
            raise RuntimeError("Chunks collection not initialized (dimensions unknown)")
        return self._chunks_col

    @property
    def file_meta_col(self) -> zvec.Collection:
        """Return file metadata collection, raising if closed."""
        if self._file_meta_col is None:
            raise RuntimeError("ZvecDocumentStore is closed (file_meta collection released)")
        return self._file_meta_col

    def __init__(self, db_path: Path, dimensions: int | None = None) -> None:
        _zvec_init_once()
        self._base_path = db_path
        self._lock = threading.Lock()

        ensure_private_dir(db_path)

        self._meta_col: zvec.Collection | None = _open_or_create_meta(db_path)
        self._dimensions = _resolve_dimensions(self._meta_col, db_path, dimensions)

        # File metadata collection (no vectors)
        fm_path = db_path / "file_metadata"
        self._file_meta_col: zvec.Collection | None
        if fm_path.exists():
            self._file_meta_col = zvec.open(path=str(fm_path))
        else:
            self._file_meta_col = zvec.create_and_open(path=str(fm_path), schema=_FILE_META_SCHEMA)

        # Chunks collection — only created once dimensions are known
        self._chunks_col: zvec.Collection | None = None
        if self._dimensions is not None:
            self._open_or_create_chunks(self._dimensions)

        # Auto-increment counter for chunk IDs
        raw_next = _read_meta(self._meta_col, "next_chunk_id")
        self._next_chunk_id = int(raw_next) if raw_next is not None else 1

    def _open_or_create_chunks(self, dimensions: int) -> None:
        chunks_path = self._base_path / "chunks"
        if chunks_path.exists():
            self._chunks_col = zvec.open(path=str(chunks_path))
        else:
            self._chunks_col = zvec.create_and_open(
                path=str(chunks_path), schema=_make_chunks_schema(dimensions)
            )

    def _alloc_ids(self, count: int) -> list[str]:
        """Allocate *count* sequential string IDs."""
        start = self._next_chunk_id
        self._next_chunk_id += count
        return [str(i) for i in range(start, start + count)]

    def _flush_counter(self) -> None:
        _write_meta(self.meta_col, "next_chunk_id", str(self._next_chunk_id))

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
            if self._chunks_col is None:
                if not embeddings:
                    return
                self._dimensions = len(embeddings[0])
                _write_meta(self.meta_col, "dimensions", str(self._dimensions))
                self._open_or_create_chunks(self._dimensions)

            chunks = self.chunks_col
            ids = self._alloc_ids(len(texts))
            docs = [
                zvec.Doc(
                    id=doc_id,
                    fields={
                        "text": text,
                        "source": source,
                        "chunk_index": i,
                        "ingested_at": ingested_at,
                    },
                    vectors={"embedding": emb},
                )
                for i, (doc_id, text, emb, source) in enumerate(
                    zip(ids, texts, embeddings, sources, strict=True)
                )
            ]
            chunks.insert(docs)
            chunks.optimize()
            self._flush_counter()

    def query(
        self,
        embedding: list[float],
        top_k: int = 5,
        source_filter: str | None = None,
    ) -> list[SearchResult]:
        with self._lock:
            if self._chunks_col is None:
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
                    # Bracket glob: over-fetch + fnmatch post-filter
                    use_fnmatch = True

            fetch_k = top_k * 10 if use_fnmatch else top_k

            kwargs: dict = {
                "topk": fetch_k,
                "output_fields": ["text", "source"],
            }
            if filter_expr is not None:
                kwargs["filter"] = filter_expr

            results = self._chunks_col.query(
                zvec.VectorQuery(field_name="embedding", vector=embedding),
                **kwargs,
            )

            search_results: list[SearchResult] = []
            for doc in results:
                source = doc.fields.get("source", "")
                if use_fnmatch and not fnmatch.fnmatch(source, source_filter):  # type: ignore[arg-type]
                    continue
                search_results.append(
                    SearchResult(
                        chunk_id=int(doc.id),
                        text=doc.fields.get("text", ""),
                        source=source,
                        distance=1.0 - float(doc.score or 0),
                    )
                )
                if len(search_results) >= top_k:
                    break

            return search_results

    def count(self) -> int:
        with self._lock:
            if self._chunks_col is None:
                return 0
            stats = self._chunks_col.stats
            return stats.doc_count

    def delete_by_source(self, source: str) -> int:
        with self._lock:
            if self._chunks_col is None:
                return 0
            # Count matching docs before deleting (delete_by_filter returns None)
            matching = self._chunks_col.query(
                filter=f"source = '{_esc(source)}'", topk=1024, output_fields=[]
            )
            if not matching:
                return 0
            self._chunks_col.delete_by_filter(filter=f"source = '{_esc(source)}'")
            return len(matching)

    # --- File metadata methods ---

    def get_file_metadata(self, source: str) -> tuple[str, float, str] | None:
        with self._lock:
            fm = self.file_meta_col
            sid = _safe_id(source)
            result = fm.fetch(ids=[sid])
            if sid not in result:
                return None
            doc = result[sid]
            return (
                doc.fields["content_hash"],
                doc.fields["last_modified"],
                doc.fields["ingested_at"],
            )

    def upsert_file_metadata(
        self,
        source: str,
        content_hash: str,
        last_modified: float,
        ingested_at: str,
        chunk_count: int,
    ) -> None:
        with self._lock:
            self.file_meta_col.upsert(
                zvec.Doc(
                    id=_safe_id(source),
                    fields={
                        "source": source,
                        "content_hash": content_hash,
                        "last_modified": last_modified,
                        "ingested_at": ingested_at,
                        "chunk_count": chunk_count,
                    },
                    vectors={"_dummy": _DUMMY_VEC_VAL},
                )
            )

    def delete_file_metadata(self, source: str) -> None:
        with self._lock:
            self.file_meta_col.delete(ids=[_safe_id(source)])

    def list_sources(self) -> list[str]:
        with self._lock:
            results = self.file_meta_col.query(topk=1024, output_fields=["source"])
            return [doc.fields["source"] for doc in results]

    def list_file_hashes(self) -> dict[str, str]:
        with self._lock:
            results = self.file_meta_col.query(topk=1024, output_fields=["source", "content_hash"])
            return {doc.fields["source"]: doc.fields["content_hash"] for doc in results}

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
            if self._chunks_col is not None:
                self._chunks_col.delete_by_filter(filter=f"source = '{_esc(source)}'")

                ids = self._alloc_ids(len(texts))
                docs = [
                    zvec.Doc(
                        id=doc_id,
                        fields={
                            "text": text,
                            "source": source,
                            "chunk_index": i,
                            "ingested_at": ingested_at,
                        },
                        vectors={"embedding": emb},
                    )
                    for i, (doc_id, text, emb) in enumerate(
                        zip(ids, texts, embeddings, strict=True)
                    )
                ]
                self._chunks_col.insert(docs)
                self._chunks_col.optimize()
                self._flush_counter()

            self.file_meta_col.upsert(
                zvec.Doc(
                    id=_safe_id(source),
                    fields={
                        "source": source,
                        "content_hash": content_hash,
                        "last_modified": last_modified,
                        "ingested_at": ingested_at,
                        "chunk_count": len(texts),
                    },
                    vectors={"_dummy": _DUMMY_VEC_VAL},
                )
            )
            return len(texts)

    def read_store_meta(self, key: str) -> str | None:
        with self._lock:
            return _read_meta(self.meta_col, key)

    def write_store_meta(self, key: str, value: str) -> None:
        with self._lock:
            _write_meta(self.meta_col, key, value)

    def close(self) -> None:
        with self._lock:
            self._flush_counter()
            _release_collection(self._chunks_col)
            _release_collection(self._file_meta_col)
            _release_collection(self._meta_col)
            self._chunks_col = None
            self._file_meta_col = None
            self._meta_col = None
            gc.collect()
