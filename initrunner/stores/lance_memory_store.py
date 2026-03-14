"""LanceDB-backed MemoryStore implementation."""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime
from pathlib import Path

import lancedb  # type: ignore[import-not-found]
import pyarrow as pa  # type: ignore[import-not-found]
import pyarrow.compute as pc  # type: ignore[import-not-found]

from initrunner._paths import ensure_private_dir
from initrunner.stores._helpers import (
    _filter_system_prompts,
    _process_loaded_messages,
)
from initrunner.stores._lance_common import (
    _ensure_meta_table,
    _esc,
    _open_db,
    _read_meta,
    _resolve_dimensions,
    _table_names,
    _write_meta,
    logger,
)
from initrunner.stores.base import (
    Memory,
    MemoryStoreBase,
    MemoryType,
    SessionSummary,
)

# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

_SESSIONS_SCHEMA = pa.schema(
    [
        pa.field("id", pa.int64()),
        pa.field("session_id", pa.string()),
        pa.field("agent_name", pa.string()),
        pa.field("timestamp", pa.string()),
        pa.field("messages_json", pa.large_string()),
    ]
)


def _make_memories_schema(dimensions: int) -> pa.Schema:
    return pa.schema(
        [
            pa.field("id", pa.int64()),
            pa.field("content", pa.large_string()),
            pa.field("category", pa.string()),
            pa.field("created_at", pa.string()),
            pa.field("memory_type", pa.string()),
            pa.field("metadata_json", pa.string()),
            pa.field("consolidated_at", pa.string()),
            pa.field("vector", pa.list_(pa.float32(), dimensions)),
        ]
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_memory_fields(row: dict) -> tuple[dict | None, MemoryType]:
    """Parse metadata_json and memory_type from a row dict, tolerating corruption."""
    meta_raw = row.get("metadata_json", "")
    try:
        meta = json.loads(meta_raw) if meta_raw else None
    except (json.JSONDecodeError, TypeError):
        logger.warning("Corrupt metadata_json, defaulting to None")
        meta = None
    mem_type_raw = row.get("memory_type", "semantic")
    try:
        mem_type = MemoryType(mem_type_raw) if mem_type_raw else MemoryType.SEMANTIC
    except ValueError:
        logger.warning("Unknown memory_type %r, defaulting to semantic", mem_type_raw)
        mem_type = MemoryType.SEMANTIC
    return meta, mem_type


def _row_to_memory(row: dict) -> Memory:
    """Convert a dict row to a Memory instance."""
    meta, mem_type = _parse_memory_fields(row)
    consolidated = row.get("consolidated_at", "")
    return Memory(
        id=int(row["id"]),
        content=row.get("content", ""),
        category=row.get("category", ""),
        created_at=row.get("created_at", ""),
        memory_type=mem_type,
        metadata=meta,
        consolidated_at=consolidated if consolidated else None,
    )


# ---------------------------------------------------------------------------
# LanceMemoryStore
# ---------------------------------------------------------------------------


class LanceMemoryStore(MemoryStoreBase):
    """Unified store for session history and long-term memories, backed by LanceDB."""

    def __init__(self, db_path: Path, dimensions: int | None = None) -> None:
        self._base_path = db_path
        self._lock = threading.Lock()
        self._ref_count = 1

        ensure_private_dir(db_path)

        self._db: lancedb.DBConnection | None = _open_db(db_path)
        _ensure_meta_table(self._db)
        self._dimensions = _resolve_dimensions(self._db, db_path, dimensions, allow_none=True)

        # Sessions table
        if "sessions" not in _table_names(self._db):
            self._db.create_table("sessions", schema=_SESSIONS_SCHEMA)

        # Memories table -- only created once dimensions are known
        self._memories_ready = False
        if self._dimensions is not None:
            self._ensure_memories_table(self._dimensions)

        # Auto-increment counters
        raw_next_session = _read_meta(self._db, "next_session_id")
        self._next_session_id = int(raw_next_session) if raw_next_session is not None else 1

        raw_next_memory = _read_meta(self._db, "next_memory_id")
        self._next_memory_id = int(raw_next_memory) if raw_next_memory is not None else 1

    def _ensure_memories_table(self, dimensions: int) -> None:
        if self._db is not None and "memories" not in _table_names(self._db):
            self._db.create_table("memories", schema=_make_memories_schema(dimensions))
        self._memories_ready = True

    def _ensure_vec_table(self, dimensions: int) -> None:
        """Lazily create the memories table when dimensions become known."""
        if self._dimensions is not None:
            return
        if self._db is None:
            raise RuntimeError("LanceMemoryStore is closed")
        _write_meta(self._db, "dimensions", str(dimensions))
        self._dimensions = dimensions
        self._ensure_memories_table(dimensions)

    def _alloc_session_id(self) -> int:
        sid = self._next_session_id
        self._next_session_id += 1
        return sid

    def _alloc_memory_id(self) -> int:
        mid = self._next_memory_id
        self._next_memory_id += 1
        return mid

    def _flush_counters(self) -> None:
        if self._db is None:
            return
        _write_meta(self._db, "next_session_id", str(self._next_session_id))
        _write_meta(self._db, "next_memory_id", str(self._next_memory_id))

    @property
    def dimensions(self) -> int | None:
        return self._dimensions

    # --- Short-term: session persistence ---

    def save_session(self, session_id: str, agent_name: str, messages: list) -> None:
        from pydantic_ai.messages import ModelMessagesTypeAdapter

        filtered = _filter_system_prompts(messages)
        data = ModelMessagesTypeAdapter.dump_json(filtered).decode("utf-8")
        with self._lock:
            if self._db is None:
                raise RuntimeError("LanceMemoryStore is closed")
            doc_id = self._alloc_session_id()
            tbl = self._db.open_table("sessions")
            tbl.add(
                [
                    {
                        "id": doc_id,
                        "session_id": session_id,
                        "agent_name": agent_name,
                        "timestamp": datetime.now(UTC).isoformat(),
                        "messages_json": data,
                    }
                ]
            )
            self._flush_counters()

    def load_latest_session(self, agent_name: str, max_messages: int = 20) -> list | None:
        with self._lock:
            if self._db is None:
                raise RuntimeError("LanceMemoryStore is closed")
            tbl = self._db.open_table("sessions")
            if tbl.count_rows() == 0:
                return None
            arrow_tbl = tbl.to_arrow()
            # Filter by agent_name
            mask = pc.equal(arrow_tbl.column("agent_name"), agent_name)  # type: ignore[unresolved-attribute]
            filtered = arrow_tbl.filter(mask)
            if filtered.num_rows == 0:
                return None
            rows = filtered.to_pylist()

        # Sort by timestamp desc, take first
        rows.sort(key=lambda d: d.get("timestamp", ""), reverse=True)
        best = rows[0]
        return _process_loaded_messages(best["messages_json"], max_messages)

    def prune_sessions(self, agent_name: str, keep_count: int = 10) -> int:
        with self._lock:
            if self._db is None:
                raise RuntimeError("LanceMemoryStore is closed")
            tbl = self._db.open_table("sessions")
            if tbl.count_rows() == 0:
                return 0
            arrow_tbl = tbl.to_arrow()
            mask = pc.equal(arrow_tbl.column("agent_name"), agent_name)  # type: ignore[unresolved-attribute]
            filtered = arrow_tbl.filter(mask)
            rows = filtered.to_pylist()

            if len(rows) <= keep_count:
                return 0

            rows.sort(key=lambda d: d.get("timestamp", ""), reverse=True)
            to_delete = rows[keep_count:]
            for row in to_delete:
                tbl.delete(f"id = {row['id']}")
            return len(to_delete)

    def list_sessions(self, agent_name: str, limit: int = 20) -> list[SessionSummary]:
        with self._lock:
            if self._db is None:
                raise RuntimeError("LanceMemoryStore is closed")
            tbl = self._db.open_table("sessions")
            if tbl.count_rows() == 0:
                return []
            arrow_tbl = tbl.to_arrow()
            mask = pc.equal(arrow_tbl.column("agent_name"), agent_name)  # type: ignore[unresolved-attribute]
            filtered = arrow_tbl.filter(mask)
            rows = filtered.to_pylist()

        # Group by session_id, keep latest timestamp per session
        session_map: dict[str, tuple[str, str]] = {}
        for row in rows:
            sid = row["session_id"]
            ts = row["timestamp"]
            if sid not in session_map or ts > session_map[sid][0]:
                session_map[sid] = (ts, row["messages_json"])

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
            if self._db is None:
                raise RuntimeError("LanceMemoryStore is closed")
            tbl = self._db.open_table("sessions")
            if tbl.count_rows() == 0:
                return None
            arrow_tbl = tbl.to_arrow()
            mask = pc.and_(  # type: ignore[unresolved-attribute]
                pc.equal(arrow_tbl.column("session_id"), session_id),  # type: ignore[unresolved-attribute]
                pc.equal(arrow_tbl.column("agent_name"), agent_name),  # type: ignore[unresolved-attribute]
            )
            filtered = arrow_tbl.filter(mask)
            rows = filtered.to_pylist()

        if not rows:
            return None
        rows.sort(key=lambda d: d.get("timestamp", ""), reverse=True)
        best = rows[0]
        return _process_loaded_messages(best["messages_json"], max_messages)

    def delete_session(self, session_id: str, agent_name: str) -> bool:
        with self._lock:
            if self._db is None:
                raise RuntimeError("LanceMemoryStore is closed")
            tbl = self._db.open_table("sessions")
            pred = f"session_id = '{_esc(session_id)}' AND agent_name = '{_esc(agent_name)}'"
            n = tbl.count_rows(pred)
            if n == 0:
                return False
            tbl.delete(pred)
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
            if self._db is None:
                raise RuntimeError("LanceMemoryStore is closed")
            self._ensure_vec_table(len(embedding))

            metadata_json = json.dumps(metadata) if metadata else ""
            now = datetime.now(UTC).isoformat()
            doc_id = self._alloc_memory_id()

            tbl = self._db.open_table("memories")
            tbl.add(
                [
                    {
                        "id": doc_id,
                        "content": content,
                        "category": category,
                        "created_at": now,
                        "memory_type": str(memory_type),
                        "metadata_json": metadata_json,
                        "consolidated_at": "",
                        "vector": embedding,
                    }
                ]
            )
            self._flush_counters()
            return doc_id

    def search_memories(
        self,
        embedding: list[float],
        top_k: int = 5,
        *,
        memory_types: list[MemoryType] | None = None,
    ) -> list[tuple[Memory, float]]:
        with self._lock:
            if self._db is None:
                raise RuntimeError("LanceMemoryStore is closed")
            if not self._memories_ready or self._dimensions is None:
                return []

            tbl = self._db.open_table("memories")
            if tbl.count_rows() == 0:
                return []

            q = tbl.search(embedding).metric("cosine").limit(top_k)  # type: ignore[unresolved-attribute]

            if memory_types is not None:
                type_clauses = [f"memory_type = '{_esc(str(t))}'" for t in memory_types]
                q = q.where(" OR ".join(type_clauses), prefilter=True)

            results = q.to_list()
            return [(_row_to_memory(row), float(row.get("_distance", 0.0))) for row in results]

    def list_memories(
        self,
        category: str | None = None,
        limit: int = 20,
        *,
        memory_type: MemoryType | None = None,
    ) -> list[Memory]:
        with self._lock:
            if self._db is None:
                raise RuntimeError("LanceMemoryStore is closed")
            if not self._memories_ready:
                return []

            tbl = self._db.open_table("memories")
            if tbl.count_rows() == 0:
                return []

            arrow_tbl = tbl.to_arrow()
            rows = arrow_tbl.to_pylist()

        # Filter in Python
        if category:
            rows = [r for r in rows if r.get("category") == category]
        if memory_type is not None:
            rows = [r for r in rows if r.get("memory_type") == str(memory_type)]

        memories = [_row_to_memory(r) for r in rows]
        memories.sort(key=lambda m: m.created_at, reverse=True)
        return memories[:limit]

    def count_memories(self, *, memory_type: MemoryType | None = None) -> int:
        with self._lock:
            if self._db is None:
                raise RuntimeError("LanceMemoryStore is closed")
            if not self._memories_ready:
                return 0

            tbl = self._db.open_table("memories")
            if memory_type is not None:
                return tbl.count_rows(f"memory_type = '{_esc(str(memory_type))}'")
            return tbl.count_rows()

    def prune_memories(
        self, keep_count: int = 1000, *, memory_type: MemoryType | None = None
    ) -> int:
        with self._lock:
            if self._db is None:
                raise RuntimeError("LanceMemoryStore is closed")
            if not self._memories_ready:
                return 0

            tbl = self._db.open_table("memories")
            arrow_tbl = tbl.to_arrow()
            rows = arrow_tbl.to_pylist()

            if memory_type is not None:
                rows = [r for r in rows if r.get("memory_type") == str(memory_type)]

            if len(rows) <= keep_count:
                return 0

            rows.sort(key=lambda d: d.get("created_at", ""), reverse=True)
            to_delete = rows[keep_count:]
            for row in to_delete:
                tbl.delete(f"id = {row['id']}")
            return len(to_delete)

    def mark_consolidated(self, memory_ids: list[int], consolidated_at: str) -> None:
        if not memory_ids:
            return
        with self._lock:
            if self._db is None:
                raise RuntimeError("LanceMemoryStore is closed")
            if not self._memories_ready:
                return
            tbl = self._db.open_table("memories")
            for mid in memory_ids:
                tbl.update(where=f"id = {mid}", values={"consolidated_at": consolidated_at})

    def get_unconsolidated_episodes(self, limit: int = 20) -> list[Memory]:
        with self._lock:
            if self._db is None:
                raise RuntimeError("LanceMemoryStore is closed")
            if not self._memories_ready:
                return []

            tbl = self._db.open_table("memories")
            if tbl.count_rows() == 0:
                return []

            arrow_tbl = tbl.to_arrow()
            rows = arrow_tbl.to_pylist()

        # Filter to episodic + unconsolidated
        unconsolidated: list[Memory] = []
        for row in rows:
            if row.get("memory_type") != "episodic":
                continue
            if row.get("consolidated_at", ""):
                continue
            unconsolidated.append(_row_to_memory(row))

        unconsolidated.sort(key=lambda m: m.created_at)
        return unconsolidated[:limit]

    # --- Lifecycle ---

    def acquire(self) -> LanceMemoryStore:
        """Increment the reference count and return *self*."""
        with self._lock:
            self._ref_count += 1
        return self

    def close(self) -> None:
        with self._lock:
            self._ref_count -= 1
            if self._ref_count > 0:
                return
            self._flush_counters()
            self._db = None
