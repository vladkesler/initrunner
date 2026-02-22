"""Zvec-backed implementations of DocumentStore and MemoryStoreBase."""

from __future__ import annotations

import fnmatch
import gc
import hashlib
import json
import shutil
import threading
from datetime import UTC, datetime
from pathlib import Path

import zvec

from initrunner._log import get_logger
from initrunner._paths import ensure_private_dir
from initrunner.stores._helpers import (
    _filter_system_prompts,
    _glob_to_sql_like,
    _process_loaded_messages,
)
from initrunner.stores.base import (
    DimensionMismatchError,
    DocumentStore,
    Memory,
    MemoryStoreBase,
    MemoryType,
    SearchResult,
    SessionSummary,
)

logger = get_logger("memory")

# ---------------------------------------------------------------------------
# Global init (once)
# ---------------------------------------------------------------------------

_zvec_initialized = False
_zvec_init_lock = threading.Lock()


def _zvec_init_once() -> None:
    global _zvec_initialized
    if _zvec_initialized:
        return
    with _zvec_init_lock:
        if _zvec_initialized:
            return
        zvec.init(
            log_type=zvec.LogType.CONSOLE,
            log_level=zvec.LogLevel.WARN,
            query_threads=4,
        )
        _zvec_initialized = True


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DUMMY_VEC = zvec.VectorSchema(
    name="_dummy",
    data_type=zvec.DataType.VECTOR_FP32,
    dimension=1,
    index_param=zvec.HnswIndexParam(metric_type=zvec.MetricType.COSINE),
)
_DUMMY_VEC_VAL = [0.0]


_META_SCHEMA = zvec.CollectionSchema(
    name="_meta",
    fields=[
        zvec.FieldSchema(name="value", data_type=zvec.DataType.STRING),
    ],
    vectors=[_DUMMY_VEC],
)


def _open_or_create_meta(base_path: Path) -> zvec.Collection:
    """Open or create the _meta key-value collection."""
    meta_path = base_path / "_meta"
    if meta_path.exists():
        return zvec.open(path=str(meta_path))
    return zvec.create_and_open(path=str(meta_path), schema=_META_SCHEMA)


def _read_meta(col: zvec.Collection, key: str) -> str | None:
    """Read a value from the _meta collection."""
    result = col.fetch(ids=[key])
    if key in result:
        return result[key].fields.get("value")
    return None


def _write_meta(col: zvec.Collection, key: str, value: str) -> None:
    """Write a key-value pair to the _meta collection."""
    col.upsert(zvec.Doc(id=key, fields={"value": value}, vectors={"_dummy": _DUMMY_VEC_VAL}))


def _resolve_dimensions(
    meta_col: zvec.Collection,
    base_path: Path,
    passed: int | None,
    *,
    allow_none: bool = False,
) -> int | None:
    """Determine the effective dimensions for a store.

    Rules:
      - Existing store + dimensions passed → validate match or raise
      - Existing store + no dimensions     → use stored value
      - New store + dimensions passed      → use passed value, write to meta
      - New store + no dimensions          → return None if allow_none, else raise
    """
    raw = _read_meta(meta_col, "dimensions")
    stored = int(raw) if raw is not None else None

    if stored is not None and passed is not None and stored != passed:
        raise DimensionMismatchError(
            f"Store at {base_path} has {stored}d embeddings but {passed}d was requested. "
            "Re-ingest with --force or use a new store_path to switch models."
        )

    if stored is not None:
        return stored

    if passed is not None:
        _write_meta(meta_col, "dimensions", str(passed))
        return passed

    if allow_none:
        return None

    raise DimensionMismatchError(
        f"Store at {base_path} has no recorded dimensions and none were provided. "
        "Pass dimensions explicitly or ingest documents first."
    )


def _esc(val: str) -> str:
    """Escape single quotes in zvec filter values."""
    return val.replace("'", "''")


def _parse_memory_fields(f: dict) -> tuple[dict | None, MemoryType]:
    """Parse metadata_json and memory_type from a zvec doc, tolerating corruption."""
    meta_raw = f.get("metadata_json", "")
    try:
        meta = json.loads(meta_raw) if meta_raw else None
    except (json.JSONDecodeError, TypeError):
        logger.warning("Corrupt metadata_json, defaulting to None")
        meta = None
    mem_type_raw = f.get("memory_type", "semantic")
    try:
        mem_type = MemoryType(mem_type_raw) if mem_type_raw else MemoryType.SEMANTIC
    except ValueError:
        logger.warning("Unknown memory_type %r, defaulting to semantic", mem_type_raw)
        mem_type = MemoryType.SEMANTIC
    return meta, mem_type


def _safe_id(key: str) -> str:
    """Convert an arbitrary string (e.g. file path) to a valid zvec doc ID."""
    return hashlib.sha256(key.encode()).hexdigest()


def _release_collection(col: zvec.Collection | None) -> None:
    """Release a zvec collection's internal C++ handle to unlock the path."""
    if col is None:
        return
    try:
        col.flush()
    except Exception as exc:
        logger.warning("Failed to flush collection: %s", exc)
    col._obj = None
    col._querier = None
    col._schema = None
    col._from_core = None  # type: ignore[invalid-assignment]


def wipe_document_store(db_path: Path) -> None:
    """Remove all data from a document store by deleting and recreating the directory."""
    if db_path.exists():
        shutil.rmtree(db_path)


# ===================================================================
# ZvecDocumentStore
# ===================================================================

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


class ZvecDocumentStore(DocumentStore):
    """Vector store for ingested documents, backed by zvec."""

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
        assert self._meta_col is not None
        _write_meta(self._meta_col, "next_chunk_id", str(self._next_chunk_id))

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
                assert self._meta_col is not None
                _write_meta(self._meta_col, "dimensions", str(self._dimensions))
                self._open_or_create_chunks(self._dimensions)

            assert self._chunks_col is not None
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
            self._chunks_col.insert(docs)
            self._chunks_col.optimize()
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
            assert self._file_meta_col is not None
            sid = _safe_id(source)
            result = self._file_meta_col.fetch(ids=[sid])
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
            assert self._file_meta_col is not None
            self._file_meta_col.upsert(
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
            assert self._file_meta_col is not None
            self._file_meta_col.delete(ids=[_safe_id(source)])

    def list_sources(self) -> list[str]:
        with self._lock:
            assert self._file_meta_col is not None
            results = self._file_meta_col.query(topk=1024, output_fields=["source"])
            return [doc.fields["source"] for doc in results]

    def list_file_hashes(self) -> dict[str, str]:
        with self._lock:
            assert self._file_meta_col is not None
            results = self._file_meta_col.query(topk=1024, output_fields=["source", "content_hash"])
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

            assert self._file_meta_col is not None
            self._file_meta_col.upsert(
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
            assert self._meta_col is not None
            return _read_meta(self._meta_col, key)

    def write_store_meta(self, key: str, value: str) -> None:
        with self._lock:
            assert self._meta_col is not None
            _write_meta(self._meta_col, key, value)

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


# ===================================================================
# ZvecMemoryStore
# ===================================================================

_SESSIONS_SCHEMA = zvec.CollectionSchema(
    name="sessions",
    fields=[
        zvec.FieldSchema(
            name="session_id",
            data_type=zvec.DataType.STRING,
            index_param=zvec.InvertIndexParam(),
        ),
        zvec.FieldSchema(
            name="agent_name",
            data_type=zvec.DataType.STRING,
            index_param=zvec.InvertIndexParam(),
        ),
        zvec.FieldSchema(name="timestamp", data_type=zvec.DataType.STRING),
        zvec.FieldSchema(name="messages_json", data_type=zvec.DataType.STRING),
    ],
    vectors=[_DUMMY_VEC],
)


def _make_memories_schema(dimensions: int) -> zvec.CollectionSchema:
    return zvec.CollectionSchema(
        name="memories",
        fields=[
            zvec.FieldSchema(name="content", data_type=zvec.DataType.STRING),
            zvec.FieldSchema(
                name="category",
                data_type=zvec.DataType.STRING,
                index_param=zvec.InvertIndexParam(),
            ),
            zvec.FieldSchema(name="created_at", data_type=zvec.DataType.STRING),
            zvec.FieldSchema(
                name="memory_type",
                data_type=zvec.DataType.STRING,
                index_param=zvec.InvertIndexParam(),
            ),
            zvec.FieldSchema(name="metadata_json", data_type=zvec.DataType.STRING, nullable=True),
            zvec.FieldSchema(name="consolidated_at", data_type=zvec.DataType.STRING, nullable=True),
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


class ZvecMemoryStore(MemoryStoreBase):
    """Unified store for session history and long-term memories, backed by zvec."""

    def __init__(self, db_path: Path, dimensions: int | None = None) -> None:
        _zvec_init_once()
        self._base_path = db_path
        self._lock = threading.Lock()
        self._ref_count = 1

        ensure_private_dir(db_path)

        self._meta_col: zvec.Collection | None = _open_or_create_meta(db_path)
        self._dimensions = _resolve_dimensions(self._meta_col, db_path, dimensions, allow_none=True)

        # Sessions collection (no vectors)
        sessions_path = db_path / "sessions"
        self._sessions_col: zvec.Collection | None
        if sessions_path.exists():
            self._sessions_col = zvec.open(path=str(sessions_path))
        else:
            self._sessions_col = zvec.create_and_open(
                path=str(sessions_path), schema=_SESSIONS_SCHEMA
            )

        # Memories collection — only created once dimensions are known
        self._memories_col: zvec.Collection | None = None
        if self._dimensions is not None:
            self._open_or_create_memories(self._dimensions)

        # Auto-increment counters
        raw_next_session = _read_meta(self._meta_col, "next_session_id")
        self._next_session_id = int(raw_next_session) if raw_next_session is not None else 1

        raw_next_memory = _read_meta(self._meta_col, "next_memory_id")
        self._next_memory_id = int(raw_next_memory) if raw_next_memory is not None else 1

    def _open_or_create_memories(self, dimensions: int) -> None:
        memories_path = self._base_path / "memories"
        if memories_path.exists():
            self._memories_col = zvec.open(path=str(memories_path))
        else:
            self._memories_col = zvec.create_and_open(
                path=str(memories_path), schema=_make_memories_schema(dimensions)
            )

    def _ensure_vec_collection(self, dimensions: int) -> None:
        """Lazily create the memories collection when dimensions become known."""
        if self._dimensions is not None:
            return
        assert self._meta_col is not None
        _write_meta(self._meta_col, "dimensions", str(dimensions))
        self._dimensions = dimensions
        self._open_or_create_memories(dimensions)

    def _alloc_session_id(self) -> str:
        sid = str(self._next_session_id)
        self._next_session_id += 1
        return sid

    def _alloc_memory_id(self) -> str:
        mid = str(self._next_memory_id)
        self._next_memory_id += 1
        return mid

    def _flush_counters(self) -> None:
        assert self._meta_col is not None
        _write_meta(self._meta_col, "next_session_id", str(self._next_session_id))
        _write_meta(self._meta_col, "next_memory_id", str(self._next_memory_id))

    @property
    def dimensions(self) -> int | None:
        return self._dimensions

    # --- Short-term: session persistence ---

    def save_session(self, session_id: str, agent_name: str, messages: list) -> None:
        from pydantic_ai.messages import ModelMessagesTypeAdapter

        filtered = _filter_system_prompts(messages)
        data = ModelMessagesTypeAdapter.dump_json(filtered).decode("utf-8")
        with self._lock:
            assert self._sessions_col is not None
            doc_id = self._alloc_session_id()
            self._sessions_col.insert(
                zvec.Doc(
                    id=doc_id,
                    fields={
                        "session_id": session_id,
                        "agent_name": agent_name,
                        "timestamp": datetime.now(UTC).isoformat(),
                        "messages_json": data,
                    },
                    vectors={"_dummy": _DUMMY_VEC_VAL},
                )
            )
            self._flush_counters()

    def load_latest_session(self, agent_name: str, max_messages: int = 20) -> list | None:
        with self._lock:
            assert self._sessions_col is not None
            results = self._sessions_col.query(
                filter=f"agent_name = '{_esc(agent_name)}'",
                topk=1024,
                output_fields=["timestamp", "messages_json"],
            )
        if not results:
            return None
        # Sort by timestamp desc, take first
        results.sort(key=lambda d: d.fields.get("timestamp", ""), reverse=True)
        best = results[0]
        return _process_loaded_messages(best.fields["messages_json"], max_messages)

    def prune_sessions(self, agent_name: str, keep_count: int = 10) -> int:
        with self._lock:
            assert self._sessions_col is not None
            results = self._sessions_col.query(
                filter=f"agent_name = '{_esc(agent_name)}'",
                topk=1024,
                output_fields=["timestamp"],
            )
            if len(results) <= keep_count:
                return 0
            results.sort(key=lambda d: d.fields.get("timestamp", ""), reverse=True)
            to_delete = [doc.id for doc in results[keep_count:]]
            if to_delete:
                self._sessions_col.delete(ids=to_delete)
            return len(to_delete)

    def list_sessions(self, agent_name: str, limit: int = 20) -> list[SessionSummary]:
        with self._lock:
            assert self._sessions_col is not None
            results = self._sessions_col.query(
                filter=f"agent_name = '{_esc(agent_name)}'",
                topk=1024,
                output_fields=["session_id", "timestamp", "messages_json"],
            )

        # Group by session_id, keep latest timestamp per session
        session_map: dict[str, tuple[str, str]] = {}
        for doc in results:
            sid = doc.fields["session_id"]
            ts = doc.fields["timestamp"]
            if sid not in session_map or ts > session_map[sid][0]:
                session_map[sid] = (ts, doc.fields["messages_json"])

        # Sort by timestamp desc, take limit
        sorted_sessions = sorted(session_map.items(), key=lambda x: x[1][0], reverse=True)[:limit]

        summaries: list[SessionSummary] = []
        for session_id, (timestamp, messages_json) in sorted_sessions:
            preview = "Untitled"
            message_count = 0
            try:
                raw = json.loads(messages_json)
                if isinstance(raw, list):
                    message_count = len(raw)
                    for msg in raw:
                        if not isinstance(msg, dict):
                            continue
                        for part in msg.get("parts", []):
                            if part.get("part_kind") == "user-prompt":
                                content = part.get("content", "")
                                if isinstance(content, str) and content.strip():
                                    preview = content.strip()[:80]
                                    break
                        if preview != "Untitled":
                            break
            except (json.JSONDecodeError, TypeError):
                pass
            summaries.append(
                SessionSummary(
                    session_id=session_id,
                    agent_name=agent_name,
                    timestamp=timestamp,
                    message_count=message_count,
                    preview=preview,
                )
            )
        return summaries

    def load_session_by_id(
        self, session_id: str, agent_name: str, max_messages: int = 20
    ) -> list | None:
        with self._lock:
            assert self._sessions_col is not None
            results = self._sessions_col.query(
                filter=f"session_id = '{_esc(session_id)}' AND agent_name = '{_esc(agent_name)}'",
                topk=1024,
                output_fields=["timestamp", "messages_json"],
            )
        if not results:
            return None
        results.sort(key=lambda d: d.fields.get("timestamp", ""), reverse=True)
        best = results[0]
        return _process_loaded_messages(best.fields["messages_json"], max_messages)

    def delete_session(self, session_id: str, agent_name: str) -> bool:
        with self._lock:
            assert self._sessions_col is not None
            results = self._sessions_col.query(
                filter=f"session_id = '{_esc(session_id)}' AND agent_name = '{_esc(agent_name)}'",
                topk=1024,
                output_fields=[],
            )
            if not results:
                return False
            assert self._sessions_col is not None
            self._sessions_col.delete(ids=[doc.id for doc in results])
            return True

    # --- Long-term: semantic memories ---

    def add_memory(
        self,
        content: str,
        category: str,
        embedding: list[float],
        *,
        memory_type: MemoryType = MemoryType.SEMANTIC,
        metadata: dict | None = None,
    ) -> int:
        MemoryType(memory_type)  # validate
        with self._lock:
            self._ensure_vec_collection(len(embedding))

            metadata_json = json.dumps(metadata) if metadata else ""
            now = datetime.now(UTC).isoformat()
            doc_id = self._alloc_memory_id()

            self._memories_col.insert(  # type: ignore[union-attr]
                zvec.Doc(
                    id=doc_id,
                    fields={
                        "content": content,
                        "category": category,
                        "created_at": now,
                        "memory_type": str(memory_type),
                        "metadata_json": metadata_json,
                        "consolidated_at": "",
                    },
                    vectors={"embedding": embedding},
                )
            )
            self._memories_col.optimize()  # type: ignore[union-attr]
            self._flush_counters()
            return int(doc_id)

    def search_memories(
        self,
        embedding: list[float],
        top_k: int = 5,
        *,
        memory_types: list[MemoryType] | None = None,
    ) -> list[tuple[Memory, float]]:
        with self._lock:
            if self._memories_col is None or self._dimensions is None:
                return []

            kwargs: dict = {
                "topk": top_k,
                "output_fields": [
                    "content",
                    "category",
                    "created_at",
                    "memory_type",
                    "metadata_json",
                    "consolidated_at",
                ],
            }

            if memory_types is not None:
                type_clauses = [f"memory_type = '{_esc(str(t))}'" for t in memory_types]
                kwargs["filter"] = " OR ".join(type_clauses)

            results = self._memories_col.query(
                zvec.VectorQuery(field_name="embedding", vector=embedding),
                **kwargs,
            )

            return self._docs_to_memories(results)

    @staticmethod
    def _docs_to_memories(docs: list) -> list[tuple[Memory, float]]:
        """Convert zvec query result docs to (Memory, distance) tuples."""
        out: list[tuple[Memory, float]] = []
        for doc in docs:
            f = doc.fields
            meta, mem_type = _parse_memory_fields(f)
            consolidated = f.get("consolidated_at", "")
            out.append(
                (
                    Memory(
                        id=int(doc.id),
                        content=f.get("content", ""),
                        category=f.get("category", ""),
                        created_at=f.get("created_at", ""),
                        memory_type=mem_type,
                        metadata=meta,
                        consolidated_at=consolidated if consolidated else None,
                    ),
                    1.0 - float(doc.score or 0),
                )
            )
        return out

    def list_memories(
        self,
        category: str | None = None,
        limit: int = 20,
        *,
        memory_type: MemoryType | None = None,
    ) -> list[Memory]:
        with self._lock:
            if self._memories_col is None:
                return []

            conditions: list[str] = []
            if category:
                conditions.append(f"category = '{_esc(category)}'")
            if memory_type is not None:
                conditions.append(f"memory_type = '{_esc(str(memory_type))}'")

            filter_expr = " AND ".join(conditions) if conditions else None

            kwargs: dict = {
                "topk": 1024,
                "output_fields": [
                    "content",
                    "category",
                    "created_at",
                    "memory_type",
                    "metadata_json",
                    "consolidated_at",
                ],
            }
            if filter_expr:
                kwargs["filter"] = filter_expr

            results = self._memories_col.query(**kwargs)

            memories: list[Memory] = []
            for doc in results:
                f = doc.fields
                meta, mem_type = _parse_memory_fields(f)
                consolidated = f.get("consolidated_at", "")
                memories.append(
                    Memory(
                        id=int(doc.id),
                        content=f.get("content", ""),
                        category=f.get("category", ""),
                        created_at=f.get("created_at", ""),
                        memory_type=mem_type,
                        metadata=meta,
                        consolidated_at=consolidated if consolidated else None,
                    )
                )

            # Sort by created_at desc, take limit
            memories.sort(key=lambda m: m.created_at, reverse=True)
            return memories[:limit]

    def count_memories(self, *, memory_type: MemoryType | None = None) -> int:
        with self._lock:
            if self._memories_col is None:
                return 0

            if memory_type is not None:
                results = self._memories_col.query(
                    filter=f"memory_type = '{_esc(str(memory_type))}'",
                    topk=1024,
                    output_fields=[],
                )
                return len(results)

            stats = self._memories_col.stats
            return stats.doc_count

    def prune_memories(
        self, keep_count: int = 1000, *, memory_type: MemoryType | None = None
    ) -> int:
        with self._lock:
            if self._memories_col is None:
                return 0

            kwargs: dict = {
                "topk": 1024,
                "output_fields": ["created_at"],
            }
            if memory_type is not None:
                kwargs["filter"] = f"memory_type = '{_esc(str(memory_type))}'"

            results = self._memories_col.query(**kwargs)

            if len(results) <= keep_count:
                return 0

            # Sort by created_at desc, keep the newest keep_count
            results.sort(key=lambda d: d.fields.get("created_at", ""), reverse=True)
            to_delete = [doc.id for doc in results[keep_count:]]
            if to_delete:
                self._memories_col.delete(ids=to_delete)
            return len(to_delete)

    def mark_consolidated(self, memory_ids: list[int], consolidated_at: str) -> None:
        if not memory_ids:
            return
        with self._lock:
            if self._memories_col is None:
                return
            str_ids = [str(mid) for mid in memory_ids]
            fetched = self._memories_col.fetch(ids=str_ids)
            for str_id in str_ids:
                if str_id in fetched:
                    doc = fetched[str_id]
                    doc.fields["consolidated_at"] = consolidated_at
                    self._memories_col.upsert(
                        zvec.Doc(id=str_id, fields=doc.fields, vectors=doc.vectors)
                    )

    def get_unconsolidated_episodes(self, limit: int = 20) -> list[Memory]:
        with self._lock:
            if self._memories_col is None:
                return []

            results = self._memories_col.query(
                filter="memory_type = 'episodic'",
                topk=1024,
                output_fields=[
                    "content",
                    "category",
                    "created_at",
                    "memory_type",
                    "metadata_json",
                    "consolidated_at",
                ],
            )

            # Filter out consolidated (non-empty consolidated_at)
            unconsolidated: list[Memory] = []
            for doc in results:
                f = doc.fields
                consolidated = f.get("consolidated_at", "")
                if consolidated:
                    continue
                meta, _ = _parse_memory_fields(f)
                unconsolidated.append(
                    Memory(
                        id=int(doc.id),
                        content=f.get("content", ""),
                        category=f.get("category", ""),
                        created_at=f.get("created_at", ""),
                        memory_type=MemoryType.EPISODIC,
                        metadata=meta,
                        consolidated_at=None,
                    )
                )

            # Sort by created_at asc, take limit
            unconsolidated.sort(key=lambda m: m.created_at)
            return unconsolidated[:limit]

    # --- Lifecycle ---

    def acquire(self) -> ZvecMemoryStore:
        """Increment the reference count and return *self*.

        Callers that ``acquire()`` a store can later ``close()`` it without
        releasing the underlying collections — the real close only happens
        when the ref-count drops to zero.
        """
        with self._lock:
            self._ref_count += 1
        return self

    def close(self) -> None:
        with self._lock:
            self._ref_count -= 1
            if self._ref_count > 0:
                return
            self._flush_counters()
            _release_collection(self._memories_col)
            _release_collection(self._sessions_col)
            _release_collection(self._meta_col)
            self._memories_col = None
            self._sessions_col = None
            self._meta_col = None
        gc.collect()
