"""SQLite-vec backed implementations of DocumentStore and MemoryStoreBase."""

from __future__ import annotations

import fnmatch
import json
import sqlite3
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import sqlite_vec
from pydantic_ai.messages import (
    ModelMessage,
    ModelMessagesTypeAdapter,
    ModelRequest,
    ModelResponse,
    SystemPromptPart,
)

from initrunner._log import get_logger
from initrunner._paths import ensure_private_dir, secure_database
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
# Shared SQL
# ---------------------------------------------------------------------------

_CREATE_STORE_META = """\
CREATE TABLE IF NOT EXISTS store_meta (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _retry_on_locked(conn, fn, max_retries=7, base_delay=0.1):
    """Execute *fn(conn)* with retries on 'database is locked' errors."""
    for attempt in range(max_retries):
        try:
            return fn(conn)
        except sqlite3.OperationalError as exc:
            if "locked" not in str(exc).lower():
                raise
            if attempt == max_retries - 1:
                logger.error("Failed to acquire DB lock after %d attempts", max_retries)
                raise
            try:
                conn.rollback()
            except Exception:
                pass
            delay = base_delay * (2**attempt)
            logger.debug(
                "Database locked, retrying in %.2fs (attempt %d/%d)",
                delay,
                attempt + 1,
                max_retries,
            )
            time.sleep(delay)


def _read_meta(conn: sqlite3.Connection, key: str) -> str | None:
    """Read a value from store_meta, returning None if table/row missing."""
    try:
        row = conn.execute("SELECT value FROM store_meta WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None
    except sqlite3.OperationalError:
        return None


def _write_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    """Write a key-value pair to store_meta."""
    conn.execute("INSERT OR REPLACE INTO store_meta (key, value) VALUES (?, ?)", (key, value))
    conn.commit()


def _resolve_dimensions(
    conn: sqlite3.Connection,
    db_path: Path,
    passed: int | None,
    *,
    allow_none: bool = False,
) -> int | None:
    """Determine the effective dimensions for a store.

    Rules:
      - Existing DB + dimensions passed → validate match or raise
      - Existing DB + no dimensions     → use stored value
      - New DB + dimensions passed      → use passed value, write to meta
      - New DB + no dimensions          → return None if allow_none, else raise
    """
    raw = _read_meta(conn, "dimensions")
    stored = int(raw) if raw is not None else None

    if stored is not None and passed is not None and stored != passed:
        raise DimensionMismatchError(
            f"Store at {db_path} has {stored}d embeddings but {passed}d was requested. "
            "Re-ingest with --force or use a new store_path to switch models."
        )

    if stored is not None:
        return stored

    if passed is not None:
        # New DB or old DB without store_meta — record for next time
        conn.execute(_CREATE_STORE_META)
        _write_meta(conn, "dimensions", str(passed))
        return passed

    if allow_none:
        return None

    raise DimensionMismatchError(
        f"Store at {db_path} has no recorded dimensions and none were provided. "
        "Pass dimensions explicitly or ingest documents first."
    )


class EmbeddingModelChangedError(Exception):
    """Raised when the embedding model has changed and the store must be wiped."""


def wipe_document_store(db_path: Path) -> None:
    """Drop all chunk data and store_meta from a document store, preserving the DB file."""
    conn = _open_sqlite_vec(db_path)
    try:
        # Drop vec table first (virtual table)
        conn.execute("DROP TABLE IF EXISTS chunks_vec")
        conn.execute("DROP TABLE IF EXISTS chunks")
        conn.execute("DELETE FROM store_meta")
        conn.execute("DROP TABLE IF EXISTS file_metadata")
        conn.commit()
    finally:
        conn.close()


def _glob_to_sql_like(pattern: str) -> str:
    """Convert a simple glob pattern to a SQL LIKE pattern.

    Handles ``*`` → ``%`` and ``?`` → ``_``, escaping literal ``%`` and ``_``.
    Does NOT handle bracket expressions (``[...]``).
    """
    like = []
    for ch in pattern:
        if ch == "*":
            like.append("%")
        elif ch == "?":
            like.append("_")
        elif ch in ("%", "_", "\\"):
            like.append("\\")
            like.append(ch)
        else:
            like.append(ch)
    return "".join(like)


def _open_sqlite_vec(db_path: Path) -> sqlite3.Connection:
    """Open a SQLite connection with sqlite-vec loaded and WAL enabled."""
    ensure_private_dir(db_path.parent)
    conn = sqlite3.connect(str(db_path), check_same_thread=False, timeout=30)
    try:
        secure_database(db_path)
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA busy_timeout=30000;")
    except Exception:
        conn.close()
        raise
    return conn


_DELETE_BATCH_SIZE = 900  # safely under SQLite's 999 variable limit

# Identifier whitelist — only these names may be interpolated into SQL.
_ALLOWED_TABLES = frozenset(
    {
        "chunks",
        "chunks_vec",
        "memories",
        "memories_vec",
        "sessions",
    }
)
_ALLOWED_COLUMNS = frozenset(
    {
        "id",
        "rowid",
        "embedding",
        "text",
        "source",
        "chunk_index",
        "ingested_at",
        "content",
        "category",
        "created_at",
        "memory_type",
        "metadata_json",
        "consolidated_at",
    }
)
_ALLOWED_DATA_EXPRS = frozenset(
    {
        "chunks.text, chunks.source",
        "memories.content, memories.category, memories.created_at",
        "memories.content, memories.category, memories.created_at, "
        "memories.memory_type, memories.metadata_json, memories.consolidated_at",
    }
)


def _safe_table(name: str) -> str:
    """Validate a table name against the allowed set."""
    if name not in _ALLOWED_TABLES:
        raise ValueError(f"Invalid SQL table name: {name!r}")
    return name


def _safe_column(name: str) -> str:
    """Validate a column name against the allowed set."""
    if name not in _ALLOWED_COLUMNS:
        raise ValueError(f"Invalid SQL column name: {name!r}")
    return name


def _safe_data_expr(expr: str) -> str:
    """Validate a data column expression against the allowed set."""
    if expr not in _ALLOWED_DATA_EXPRS:
        raise ValueError(f"Invalid SQL data expression: {expr!r}")
    return expr


# Item 7: bulk-delete helper
def _delete_by_ids(conn: sqlite3.Connection, table: str, column: str, ids: list[int]) -> None:
    """Delete rows from *table* where *column* is in *ids*."""
    if not ids:
        return
    safe_table = _safe_table(table)
    safe_col = _safe_column(column)
    for i in range(0, len(ids), _DELETE_BATCH_SIZE):
        batch = ids[i : i + _DELETE_BATCH_SIZE]
        placeholders = ",".join("?" * len(batch))
        conn.execute(f"DELETE FROM {safe_table} WHERE {safe_col} IN ({placeholders})", batch)


# Item 8: chunk insertion helper
def _insert_chunks(
    conn: sqlite3.Connection,
    texts: list[str],
    embeddings: list[list[float]],
    source: str,
    ingested_at: str,
) -> None:
    """Insert text chunks and their embeddings into chunks + chunks_vec."""
    for i, (text, embedding) in enumerate(zip(texts, embeddings, strict=True)):
        cursor = conn.execute(
            "INSERT INTO chunks (text, source, chunk_index, ingested_at) VALUES (?, ?, ?, ?)",
            (text, source, i, ingested_at),
        )
        conn.execute(
            "INSERT INTO chunks_vec (rowid, embedding) VALUES (?, ?)",
            (cursor.lastrowid, sqlite_vec.serialize_float32(embedding)),
        )


def _vec_search(
    conn: sqlite3.Connection,
    vec_table: str,
    data_table: str,
    join_col: str,
    data_cols: str,
    embedding: list[float],
    k: int,
) -> list[tuple]:
    """Run a vector MATCH query and join with the data table. Returns raw rows."""
    vt = _safe_table(vec_table)
    dt = _safe_table(data_table)
    jc = _safe_column(join_col)
    dc = _safe_data_expr(data_cols)
    return conn.execute(
        f"""
        SELECT {vt}.rowid, {vt}.distance, {dc}
        FROM {vt}
        LEFT JOIN {dt} ON {dt}.{jc} = {vt}.rowid
        WHERE embedding MATCH ?
        AND k = ?
        ORDER BY distance
        """,
        (sqlite_vec.serialize_float32(embedding), k),
    ).fetchall()


def _rows_to_search_results(rows: list[tuple]) -> list[SearchResult]:
    """Map (rowid, distance, text, source) tuples to SearchResult."""
    return [
        SearchResult(chunk_id=row[0], distance=row[1], text=row[2], source=row[3]) for row in rows
    ]


def _filtered_vec_search(
    conn: sqlite3.Connection,
    embedding: list[float],
    top_k: int,
    *,
    candidate_ids: set[int] | None = None,
    predicate: Callable[[tuple], bool] | None = None,
) -> list[SearchResult]:
    """Run a vector search with optional post-filtering.

    Parameters:
        candidate_ids: If given, only include rows whose rowid is in this set.
            Over-fetches to ``max(top_k, len(candidate_ids))`` to compensate.
        predicate: If given (and no *candidate_ids*), only include rows
            matching this callable.  Over-fetches ``top_k * 10``.
    """
    if candidate_ids is not None:
        fetch_k = max(top_k, len(candidate_ids))
    elif predicate is not None:
        fetch_k = top_k * 10
    else:
        fetch_k = top_k

    rows = _vec_search(
        conn,
        "chunks_vec",
        "chunks",
        "id",
        "chunks.text, chunks.source",
        embedding,
        fetch_k,
    )

    if candidate_ids is not None:
        rows = [r for r in rows if r[0] in candidate_ids]
    elif predicate is not None:
        rows = [r for r in rows if predicate(r)]

    return _rows_to_search_results(rows)[:top_k]


def _delete_chunks_by_source(conn: sqlite3.Connection, source: str) -> list[int]:
    """Delete chunks and their vec entries for a given source. Returns deleted IDs."""
    rows = conn.execute("SELECT id FROM chunks WHERE source = ?", (source,)).fetchall()
    ids = [r[0] for r in rows]
    _delete_by_ids(conn, "chunks_vec", "rowid", ids)
    _delete_by_ids(conn, "chunks", "id", ids)
    return ids


# Item 10: unified legacy dimension migration
def _migrate_legacy_dimensions(conn: sqlite3.Connection, vec_table: str) -> None:
    """For pre-existing DBs without store_meta dimensions, default to 1536."""
    _safe_table(vec_table)  # validate even though parameterised
    if _read_meta(conn, "dimensions") is not None:
        return
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (vec_table,)
    ).fetchone()
    if row is not None:
        _write_meta(conn, "dimensions", "1536")


def _init_store_common(
    db_path: Path,
    vec_table_name: str,
    dimensions: int | None,
    *,
    allow_none: bool = False,
) -> tuple[sqlite3.Connection, int | None]:
    """Shared init: open connection, create store_meta, migrate, resolve dimensions."""
    conn = _open_sqlite_vec(db_path)
    try:

        def _init(c):
            c.execute(_CREATE_STORE_META)
            c.commit()

        _retry_on_locked(conn, _init)
        _migrate_legacy_dimensions(conn, vec_table_name)
        resolved = _resolve_dimensions(conn, db_path, dimensions, allow_none=allow_none)
    except Exception:
        conn.close()
        raise
    return conn, resolved


# ===================================================================
# SqliteVecDocumentStore
# ===================================================================

_CREATE_CHUNKS = """\
CREATE TABLE IF NOT EXISTS chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    text TEXT NOT NULL,
    source TEXT NOT NULL,
    chunk_index INTEGER NOT NULL,
    ingested_at TEXT NOT NULL DEFAULT ''
);
"""

_CREATE_SOURCE_INDEX = "CREATE INDEX IF NOT EXISTS idx_chunks_source ON chunks (source);"

_CREATE_FILE_METADATA = """\
CREATE TABLE IF NOT EXISTS file_metadata (
    source TEXT PRIMARY KEY,
    content_hash TEXT NOT NULL,
    last_modified REAL NOT NULL,
    ingested_at TEXT NOT NULL,
    chunk_count INTEGER NOT NULL DEFAULT 0
);
"""


class SqliteVecDocumentStore(DocumentStore):
    """Vector store for ingested documents, backed by sqlite-vec."""

    def __init__(self, db_path: Path, dimensions: int | None = None) -> None:
        self._db_path = db_path
        self._conn, self._dimensions = _init_store_common(db_path, "chunks_vec", dimensions)
        self._lock = threading.Lock()

        try:
            # Schema tables (non-vec)
            self._conn.execute(_CREATE_CHUNKS)
            self._conn.execute(_CREATE_SOURCE_INDEX)
            self._conn.execute(_CREATE_FILE_METADATA)
            self._conn.commit()

            # Ensure vec table exists
            self._conn.execute(
                f"CREATE VIRTUAL TABLE IF NOT EXISTS chunks_vec "
                f"USING vec0(embedding float[{self._dimensions}]);"
            )
            self._conn.commit()

            self._migrate()
        except Exception:
            self._conn.close()
            raise

    def _migrate(self) -> None:
        """Run schema migrations for existing databases."""

        def _do(c):
            columns = {row[1] for row in c.execute("PRAGMA table_info(chunks)").fetchall()}
            if "ingested_at" not in columns:
                c.execute("ALTER TABLE chunks ADD COLUMN ingested_at TEXT NOT NULL DEFAULT ''")
                c.commit()

        _retry_on_locked(self._conn, _do)

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
            for text, embedding, source in zip(texts, embeddings, sources, strict=True):
                _insert_chunks(self._conn, [text], [embedding], source, ingested_at)
            self._conn.commit()

    def query(
        self,
        embedding: list[float],
        top_k: int = 5,
        source_filter: str | None = None,
    ) -> list[SearchResult]:
        with self._lock:
            if source_filter is None:
                return _filtered_vec_search(self._conn, embedding, top_k)

            is_glob = "*" in source_filter or "?" in source_filter

            if not is_glob:
                # Exact source match
                candidate_ids = self._source_ids(source_filter)
                if not candidate_ids:
                    return []
                return _filtered_vec_search(
                    self._conn, embedding, top_k, candidate_ids=candidate_ids
                )

            # Glob pattern: use SQL LIKE pre-filter when no bracket expressions
            if "[" not in source_filter:
                like_pattern = _glob_to_sql_like(source_filter)
                id_rows = self._conn.execute(
                    "SELECT id FROM chunks WHERE source LIKE ? ESCAPE '\\'",
                    (like_pattern,),
                ).fetchall()
                if not id_rows:
                    return []
                candidate_ids = {r[0] for r in id_rows}
                return _filtered_vec_search(
                    self._conn, embedding, top_k, candidate_ids=candidate_ids
                )

            # Bracket glob: fall back to over-fetch + fnmatch
            sf = source_filter  # capture for lambda
            return _filtered_vec_search(
                self._conn, embedding, top_k, predicate=lambda r: fnmatch.fnmatch(r[3], sf)
            )

    def _source_ids(self, source: str) -> set[int]:
        """Return chunk IDs matching an exact source string."""
        id_rows = self._conn.execute("SELECT id FROM chunks WHERE source = ?", (source,)).fetchall()
        return {r[0] for r in id_rows}

    def count(self) -> int:
        with self._lock:
            row = self._conn.execute("SELECT COUNT(*) FROM chunks").fetchone()
            return row[0] if row else 0

    def delete_by_source(self, source: str) -> int:
        with self._lock:
            ids = _delete_chunks_by_source(self._conn, source)
            if ids:
                self._conn.commit()
            return len(ids)

    # --- File metadata methods ---

    def get_file_metadata(self, source: str) -> tuple[str, float, str] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT content_hash, last_modified, ingested_at "
                "FROM file_metadata WHERE source = ?",
                (source,),
            ).fetchone()
            return (row[0], row[1], row[2]) if row else None

    def upsert_file_metadata(
        self,
        source: str,
        content_hash: str,
        last_modified: float,
        ingested_at: str,
        chunk_count: int,
    ) -> None:
        with self._lock:
            self._conn.execute(
                """INSERT INTO file_metadata
                (source, content_hash, last_modified, ingested_at, chunk_count)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(source) DO UPDATE SET
                    content_hash=excluded.content_hash,
                    last_modified=excluded.last_modified,
                    ingested_at=excluded.ingested_at,
                    chunk_count=excluded.chunk_count
                """,
                (source, content_hash, last_modified, ingested_at, chunk_count),
            )
            self._conn.commit()

    def delete_file_metadata(self, source: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM file_metadata WHERE source = ?", (source,))
            self._conn.commit()

    def list_sources(self) -> list[str]:
        with self._lock:
            rows = self._conn.execute("SELECT source FROM file_metadata").fetchall()
            return [r[0] for r in rows]

    def list_file_hashes(self) -> dict[str, str]:
        with self._lock:
            rows = self._conn.execute("SELECT source, content_hash FROM file_metadata").fetchall()
            return {row[0]: row[1] for row in rows}

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
            try:
                _delete_chunks_by_source(self._conn, source)
                _insert_chunks(self._conn, texts, embeddings, source, ingested_at)
                self._conn.execute(
                    """INSERT INTO file_metadata
                    (source, content_hash, last_modified, ingested_at, chunk_count)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(source) DO UPDATE SET
                        content_hash=excluded.content_hash,
                        last_modified=excluded.last_modified,
                        ingested_at=excluded.ingested_at,
                        chunk_count=excluded.chunk_count
                    """,
                    (source, content_hash, last_modified, ingested_at, len(texts)),
                )
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise

            return len(texts)

    def close(self) -> None:
        with self._lock:
            self._conn.close()


# ===================================================================
# SqliteVecMemoryStore
# ===================================================================


def _process_loaded_messages(
    json_data: bytes | str, max_messages: int
) -> list[ModelMessage] | None:
    """Parse, trim, and validate a stored message list."""
    messages: list[ModelMessage] = list(ModelMessagesTypeAdapter.validate_json(json_data))
    if not messages:
        return None
    if len(messages) > max_messages:
        messages = messages[-max_messages:]
    while messages and isinstance(messages[0], ModelResponse):
        messages.pop(0)
    return messages if messages else None


class SqliteVecMemoryStore(MemoryStoreBase):
    """Unified store for session history and long-term memories, backed by sqlite-vec."""

    def __init__(self, db_path: Path, dimensions: int | None = None) -> None:
        self._db_path = db_path
        self._conn, self._dimensions = _init_store_common(
            db_path, "memories_vec", dimensions, allow_none=True
        )
        self._lock = threading.Lock()
        try:
            self._init_tables()
        except Exception:
            self._conn.close()
            raise

    def _init_tables(self) -> None:
        dims = self._dimensions

        def _do(c):
            c.execute(
                """\
                CREATE TABLE IF NOT EXISTS sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    agent_name TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    messages_json TEXT NOT NULL
                );"""
            )
            c.execute(
                "CREATE INDEX IF NOT EXISTS idx_sessions_agent "
                "ON sessions (agent_name, timestamp DESC);"
            )
            c.execute(
                """\
                CREATE TABLE IF NOT EXISTS memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    content TEXT NOT NULL,
                    category TEXT NOT NULL DEFAULT 'general',
                    created_at TEXT NOT NULL,
                    memory_type TEXT NOT NULL DEFAULT 'semantic'
                        CHECK(memory_type IN ('episodic', 'semantic', 'procedural')),
                    metadata_json TEXT,
                    consolidated_at TEXT
                );"""
            )
            c.execute("CREATE INDEX IF NOT EXISTS idx_memories_category ON memories (category);")
            # Only create vec table if we know the dimensions
            if dims is not None:
                c.execute(
                    f"CREATE VIRTUAL TABLE IF NOT EXISTS memories_vec "
                    f"USING vec0(embedding float[{dims}]);"
                )
            c.commit()

        _retry_on_locked(self._conn, _do)
        self._migrate_memory_columns()

    def _migrate_memory_columns(self) -> None:
        """Add memory_type, metadata_json, consolidated_at columns to existing DBs."""

        def _do(c):
            columns = {row[1] for row in c.execute("PRAGMA table_info(memories)").fetchall()}
            if "memory_type" not in columns:
                c.execute(
                    "ALTER TABLE memories ADD COLUMN memory_type TEXT NOT NULL DEFAULT 'semantic'"
                )
            if "metadata_json" not in columns:
                c.execute("ALTER TABLE memories ADD COLUMN metadata_json TEXT")
            if "consolidated_at" not in columns:
                c.execute("ALTER TABLE memories ADD COLUMN consolidated_at TEXT")
            c.execute("CREATE INDEX IF NOT EXISTS idx_memories_type ON memories (memory_type);")
            c.execute(
                "CREATE INDEX IF NOT EXISTS idx_memories_type_category "
                "ON memories (memory_type, category);"
            )
            c.commit()

        _retry_on_locked(self._conn, _do)

    def _ensure_vec_table(self, dimensions: int) -> None:
        """Lazily create the memories_vec table when dimensions become known."""
        with self._lock:
            if self._dimensions is not None:
                return

            def _do(c):
                c.execute(_CREATE_STORE_META)
                c.execute(
                    "INSERT OR REPLACE INTO store_meta (key, value) VALUES (?, ?)",
                    ("dimensions", str(dimensions)),
                )
                c.execute(
                    f"CREATE VIRTUAL TABLE IF NOT EXISTS memories_vec "
                    f"USING vec0(embedding float[{dimensions}]);"
                )
                c.commit()

            _retry_on_locked(self._conn, _do)
            self._dimensions = dimensions

    @property
    def dimensions(self) -> int | None:
        return self._dimensions

    # --- Short-term: session persistence ---

    def save_session(self, session_id: str, agent_name: str, messages: list[ModelMessage]) -> None:
        filtered = _filter_system_prompts(messages)
        data = ModelMessagesTypeAdapter.dump_json(filtered).decode("utf-8")
        with self._lock:
            self._conn.execute(
                "INSERT INTO sessions (session_id, agent_name, timestamp, messages_json) "
                "VALUES (?, ?, ?, ?)",
                (session_id, agent_name, datetime.now(UTC).isoformat(), data),
            )
            self._conn.commit()

    def load_latest_session(
        self, agent_name: str, max_messages: int = 20
    ) -> list[ModelMessage] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT messages_json FROM sessions WHERE agent_name = ? "
                "ORDER BY timestamp DESC LIMIT 1",
                (agent_name,),
            ).fetchone()
        if row is None:
            return None
        return _process_loaded_messages(row[0], max_messages)

    def prune_sessions(self, agent_name: str, keep_count: int = 10) -> int:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id FROM sessions WHERE agent_name = ? ORDER BY timestamp DESC",
                (agent_name,),
            ).fetchall()
            to_delete = [r[0] for r in rows[keep_count:]]
            _delete_by_ids(self._conn, "sessions", "id", to_delete)
            if to_delete:
                self._conn.commit()
            return len(to_delete)

    def list_sessions(self, agent_name: str, limit: int = 20) -> list[SessionSummary]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT session_id, MAX(timestamp) AS ts, messages_json "
                "FROM sessions WHERE agent_name = ? "
                "GROUP BY session_id ORDER BY ts DESC LIMIT ?",
                (agent_name, limit),
            ).fetchall()

        results: list[SessionSummary] = []
        for session_id, timestamp, messages_json in rows:
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
            results.append(
                SessionSummary(
                    session_id=session_id,
                    agent_name=agent_name,
                    timestamp=timestamp,
                    message_count=message_count,
                    preview=preview,
                )
            )
        return results

    def load_session_by_id(
        self, session_id: str, agent_name: str, max_messages: int = 20
    ) -> list[ModelMessage] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT messages_json FROM sessions "
                "WHERE session_id = ? AND agent_name = ? "
                "ORDER BY timestamp DESC LIMIT 1",
                (session_id, agent_name),
            ).fetchone()
        if row is None:
            return None
        return _process_loaded_messages(row[0], max_messages)

    def delete_session(self, session_id: str, agent_name: str) -> bool:
        with self._lock:
            cursor = self._conn.execute(
                "DELETE FROM sessions WHERE session_id = ? AND agent_name = ?",
                (session_id, agent_name),
            )
            self._conn.commit()
            return cursor.rowcount > 0

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
        # Validate memory_type
        MemoryType(memory_type)
        self._ensure_vec_table(len(embedding))
        metadata_json = json.dumps(metadata) if metadata else None
        with self._lock:

            def _do(c):
                now = datetime.now(UTC).isoformat()
                cursor = c.execute(
                    "INSERT INTO memories "
                    "(content, category, created_at, memory_type, metadata_json) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (content, category, now, str(memory_type), metadata_json),
                )
                row_id = cursor.lastrowid
                c.execute(
                    "INSERT INTO memories_vec (rowid, embedding) VALUES (?, ?)",
                    (row_id, sqlite_vec.serialize_float32(embedding)),
                )
                c.commit()
                return row_id

            return _retry_on_locked(self._conn, _do)

    def search_memories(
        self,
        embedding: list[float],
        top_k: int = 5,
        *,
        memory_types: list[MemoryType] | None = None,
    ) -> list[tuple[Memory, float]]:
        with self._lock:
            if self._dimensions is None:
                return []

            data_cols = (
                "memories.content, memories.category, memories.created_at, "
                "memories.memory_type, memories.metadata_json, memories.consolidated_at"
            )

            if memory_types is None:
                rows = _vec_search(
                    self._conn,
                    "memories_vec",
                    "memories",
                    "id",
                    data_cols,
                    embedding,
                    top_k,
                )
                return self._rows_to_memories(rows)

            # Iterative overfetch for type-filtered search
            type_set = {str(t) for t in memory_types}
            total_count = self._conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
            if total_count == 0:
                return []

            fetch_k = min(top_k * 2, total_count)
            collected: list[tuple] = []

            while True:
                rows = _vec_search(
                    self._conn,
                    "memories_vec",
                    "memories",
                    "id",
                    data_cols,
                    embedding,
                    fetch_k,
                )
                collected = [r for r in rows if r[5] in type_set]
                if len(collected) >= top_k or fetch_k >= total_count:
                    break
                fetch_k = min(fetch_k * 2, total_count)

            return self._rows_to_memories(collected[:top_k])

    @staticmethod
    def _rows_to_memories(rows: list[tuple]) -> list[tuple[Memory, float]]:
        """Convert raw rows to (Memory, distance) tuples."""
        results: list[tuple[Memory, float]] = []
        for row in rows:
            meta = json.loads(row[6]) if row[6] else None
            mem_type = MemoryType(row[5]) if row[5] else MemoryType.SEMANTIC
            results.append(
                (
                    Memory(
                        id=row[0],
                        content=row[2],
                        category=row[3],
                        created_at=row[4],
                        memory_type=mem_type,
                        metadata=meta,
                        consolidated_at=row[7] if len(row) > 7 else None,
                    ),
                    row[1],
                )
            )
        return results

    def list_memories(
        self,
        category: str | None = None,
        limit: int = 20,
        *,
        memory_type: MemoryType | None = None,
    ) -> list[Memory]:
        with self._lock:
            conditions: list[str] = []
            params: list[object] = []
            if category:
                conditions.append("category = ?")
                params.append(category)
            if memory_type is not None:
                conditions.append("memory_type = ?")
                params.append(str(memory_type))
            where = (" WHERE " + " AND ".join(conditions)) if conditions else ""
            params.append(limit)
            rows = self._conn.execute(
                f"SELECT id, content, category, created_at, memory_type, metadata_json, "
                f"consolidated_at FROM memories{where} ORDER BY created_at DESC LIMIT ?",
                params,
            ).fetchall()
            return [
                Memory(
                    id=r[0],
                    content=r[1],
                    category=r[2],
                    created_at=r[3],
                    memory_type=MemoryType(r[4]) if r[4] else MemoryType.SEMANTIC,
                    metadata=json.loads(r[5]) if r[5] else None,
                    consolidated_at=r[6],
                )
                for r in rows
            ]

    def count_memories(self, *, memory_type: MemoryType | None = None) -> int:
        with self._lock:
            if memory_type is not None:
                row = self._conn.execute(
                    "SELECT COUNT(*) FROM memories WHERE memory_type = ?",
                    (str(memory_type),),
                ).fetchone()
            else:
                row = self._conn.execute("SELECT COUNT(*) FROM memories").fetchone()
            return row[0] if row else 0

    def prune_memories(
        self, keep_count: int = 1000, *, memory_type: MemoryType | None = None
    ) -> int:
        with self._lock:
            if memory_type is not None:
                rows = self._conn.execute(
                    "SELECT id FROM memories WHERE memory_type = ? ORDER BY created_at DESC",
                    (str(memory_type),),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT id FROM memories ORDER BY created_at DESC",
                ).fetchall()
            to_delete = [r[0] for r in rows[keep_count:]]
            _delete_by_ids(self._conn, "memories_vec", "rowid", to_delete)
            _delete_by_ids(self._conn, "memories", "id", to_delete)
            if to_delete:
                self._conn.commit()
            return len(to_delete)

    def mark_consolidated(self, memory_ids: list[int], consolidated_at: str) -> None:
        if not memory_ids:
            return
        with self._lock:
            for i in range(0, len(memory_ids), _DELETE_BATCH_SIZE):
                batch = memory_ids[i : i + _DELETE_BATCH_SIZE]
                placeholders = ",".join("?" * len(batch))
                self._conn.execute(
                    f"UPDATE memories SET consolidated_at = ? WHERE id IN ({placeholders})",
                    [consolidated_at, *batch],
                )
            self._conn.commit()

    def get_unconsolidated_episodes(self, limit: int = 20) -> list[Memory]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, content, category, created_at, memory_type, metadata_json, "
                "consolidated_at FROM memories "
                "WHERE memory_type = 'episodic' AND consolidated_at IS NULL "
                "ORDER BY created_at ASC LIMIT ?",
                (limit,),
            ).fetchall()
            return [
                Memory(
                    id=r[0],
                    content=r[1],
                    category=r[2],
                    created_at=r[3],
                    memory_type=MemoryType(r[4]) if r[4] else MemoryType.EPISODIC,
                    metadata=json.loads(r[5]) if r[5] else None,
                    consolidated_at=r[6],
                )
                for r in rows
            ]

    # --- Lifecycle ---

    def close(self) -> None:
        with self._lock:
            self._conn.close()


# ---------------------------------------------------------------------------
# Module-level helper (used by tests)
# ---------------------------------------------------------------------------


def _filter_system_prompts(messages: list[ModelMessage]) -> list[ModelMessage]:
    """Return messages with SystemPromptPart entries removed from ModelRequest parts."""
    filtered: list[ModelMessage] = []
    for msg in messages:
        if isinstance(msg, ModelRequest):
            new_parts = [p for p in msg.parts if not isinstance(p, SystemPromptPart)]
            if new_parts:
                filtered.append(ModelRequest(parts=new_parts))
        else:
            filtered.append(msg)
    return filtered
