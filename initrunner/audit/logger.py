"""Append-only SQLite audit log."""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, TypeVar

from initrunner._log import get_logger
from initrunner._paths import ensure_private_dir, secure_database
from initrunner.audit._redact import scrub_secrets

if TYPE_CHECKING:
    from initrunner.agent.executor import RunResult
    from initrunner.agent.schema import RoleDefinition

logger = get_logger("audit")


@dataclass
class DelegateAuditEvent:
    """Audit record for inter-service delegate routing outcomes."""

    timestamp: str
    source_service: str
    target_service: str
    status: str  # "delivered" | "dropped" | "filtered" | "error"
    source_run_id: str
    reason: str | None  # None for delivered; payload.error / "queue_full" / str(exc)
    trace: str | None  # Comma-separated service chain e.g. "a,b,c"
    payload_preview: str  # First 200 chars of payload output, secret-scrubbed


@dataclass
class AuditRecord:
    run_id: str
    agent_name: str
    timestamp: str
    user_prompt: str
    model: str
    provider: str
    output: str
    tokens_in: int
    tokens_out: int
    total_tokens: int
    tool_calls: int
    duration_ms: int
    success: bool
    error: str | None = None
    trigger_type: str | None = None
    trigger_metadata: str | None = None

    @classmethod
    def from_run(
        cls,
        result: RunResult,
        role: RoleDefinition,
        prompt: str,
        *,
        output_override: str | None = None,
        trigger_type: str | None = None,
        trigger_metadata: dict[str, str] | None = None,
    ) -> AuditRecord:
        """Build an AuditRecord from a RunResult and role definition."""
        return cls(
            run_id=result.run_id,
            agent_name=role.metadata.name,
            timestamp=datetime.now(UTC).isoformat(),
            user_prompt=prompt,
            model=role.spec.model.name,
            provider=role.spec.model.provider,
            output=output_override if output_override is not None else result.output,
            tokens_in=result.tokens_in,
            tokens_out=result.tokens_out,
            total_tokens=result.total_tokens,
            tool_calls=result.tool_calls,
            duration_ms=result.duration_ms,
            success=result.success,
            error=result.error,
            trigger_type=trigger_type,
            trigger_metadata=json.dumps(trigger_metadata) if trigger_metadata else None,
        )


_CREATE_TABLE = """\
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    agent_name TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    user_prompt TEXT NOT NULL,
    model TEXT NOT NULL,
    provider TEXT NOT NULL,
    output TEXT NOT NULL,
    tokens_in INTEGER NOT NULL,
    tokens_out INTEGER NOT NULL,
    total_tokens INTEGER NOT NULL,
    tool_calls INTEGER NOT NULL,
    duration_ms INTEGER NOT NULL,
    success BOOLEAN NOT NULL,
    error TEXT,
    trigger_type TEXT,
    trigger_metadata TEXT
);
"""

_CREATE_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_agent_name ON audit_log (agent_name);",
    "CREATE INDEX IF NOT EXISTS idx_timestamp ON audit_log (timestamp);",
    "CREATE INDEX IF NOT EXISTS idx_run_id ON audit_log (run_id);",
    "CREATE INDEX IF NOT EXISTS idx_trigger_type ON audit_log (trigger_type);",
]

_INSERT = """\
INSERT INTO audit_log (
    run_id, agent_name, timestamp, user_prompt, model, provider,
    output, tokens_in, tokens_out, total_tokens, tool_calls,
    duration_ms, success, error, trigger_type, trigger_metadata
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
"""

_CREATE_SECURITY_EVENTS_TABLE = """\
CREATE TABLE IF NOT EXISTS security_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    event_type TEXT NOT NULL,
    agent_name TEXT NOT NULL,
    details TEXT NOT NULL,
    source_ip TEXT
);
"""

_CREATE_SECURITY_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_sec_event_type ON security_events (event_type);",
    "CREATE INDEX IF NOT EXISTS idx_sec_timestamp ON security_events (timestamp);",
    "CREATE INDEX IF NOT EXISTS idx_sec_agent ON security_events (agent_name);",
]

_INSERT_SECURITY_EVENT = """\
INSERT INTO security_events (timestamp, event_type, agent_name, details, source_ip)
VALUES (?, ?, ?, ?, ?);
"""

_CREATE_DELEGATE_EVENTS_TABLE = """\
CREATE TABLE IF NOT EXISTS delegate_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    source_service TEXT NOT NULL,
    target_service TEXT NOT NULL,
    status TEXT NOT NULL,
    source_run_id TEXT NOT NULL,
    reason TEXT,
    trace TEXT,
    payload_preview TEXT NOT NULL
);
"""

_CREATE_DELEGATE_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_del_source ON delegate_events (source_service);",
    "CREATE INDEX IF NOT EXISTS idx_del_target ON delegate_events (target_service);",
    "CREATE INDEX IF NOT EXISTS idx_del_status ON delegate_events (status);",
    "CREATE INDEX IF NOT EXISTS idx_del_timestamp ON delegate_events (timestamp);",
    "CREATE INDEX IF NOT EXISTS idx_del_run_id ON delegate_events (source_run_id);",
]

_INSERT_DELEGATE_EVENT = """\
INSERT INTO delegate_events (
    timestamp, source_service, target_service, status,
    source_run_id, reason, trace, payload_preview
) VALUES (?, ?, ?, ?, ?, ?, ?, ?);
"""


def _default_db_path() -> Path:
    from initrunner.config import get_audit_db_path

    return get_audit_db_path()


class _LazyDbPath:
    """Lazy-evaluated default DB path to avoid import-time filesystem access."""

    _value: Path | None = None

    def _resolve(self) -> Path:
        if self._value is None:
            self._value = _default_db_path()
        return self._value

    def __fspath__(self) -> str:
        return str(self._resolve())

    def __str__(self) -> str:
        return str(self._resolve())

    def __repr__(self) -> str:
        return f"_LazyDbPath({self._resolve()!r})"

    def __truediv__(self, other: str) -> Path:
        return self._resolve() / other

    def __getattr__(self, name: str):
        # Delegate any attribute access (exists, parent, etc.) to the resolved Path
        return getattr(self._resolve(), name)


DEFAULT_DB_PATH: _LazyDbPath = _LazyDbPath()


def _migrate_add_trigger_columns(conn: sqlite3.Connection) -> None:
    """Idempotent migration: add trigger columns to existing DBs."""
    try:
        conn.execute("ALTER TABLE audit_log ADD COLUMN trigger_type TEXT")
    except sqlite3.OperationalError:
        pass  # Column already exists
    try:
        conn.execute("ALTER TABLE audit_log ADD COLUMN trigger_metadata TEXT")
    except sqlite3.OperationalError:
        pass  # Column already exists


def _build_where(
    filters: list[tuple[str, object]],
) -> tuple[str, list[object]]:
    """Build a WHERE clause from (column_expr, value) pairs.

    Returns (where_fragment, params). If no filters, returns ("", []).
    """
    clauses: list[str] = []
    params: list[object] = []
    for clause, value in filters:
        clauses.append(clause)
        params.append(value)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    return where, params


def _row_to_delegate_event(row: sqlite3.Row) -> DelegateAuditEvent:
    """Convert a sqlite3.Row to a DelegateAuditEvent."""
    return DelegateAuditEvent(
        timestamp=row["timestamp"],
        source_service=row["source_service"],
        target_service=row["target_service"],
        status=row["status"],
        source_run_id=row["source_run_id"],
        reason=row["reason"],
        trace=row["trace"],
        payload_preview=row["payload_preview"],
    )


def _row_to_record(row: sqlite3.Row) -> AuditRecord:
    """Convert a sqlite3.Row to an AuditRecord."""
    return AuditRecord(
        run_id=row["run_id"],
        agent_name=row["agent_name"],
        timestamp=row["timestamp"],
        user_prompt=row["user_prompt"],
        model=row["model"],
        provider=row["provider"],
        output=row["output"],
        tokens_in=row["tokens_in"],
        tokens_out=row["tokens_out"],
        total_tokens=row["total_tokens"],
        tool_calls=row["tool_calls"],
        duration_ms=row["duration_ms"],
        success=bool(row["success"]),
        error=row["error"],
        trigger_type=row["trigger_type"],
        trigger_metadata=row["trigger_metadata"],
    )


_RECORD_FIELDS = [
    "run_id",
    "agent_name",
    "timestamp",
    "user_prompt",
    "model",
    "provider",
    "output",
    "tokens_in",
    "tokens_out",
    "total_tokens",
    "tool_calls",
    "duration_ms",
    "success",
    "error",
    "trigger_type",
    "trigger_metadata",
]


def record_to_dict(record: AuditRecord, *, parse_trigger_metadata: bool = False) -> dict:
    """Convert an AuditRecord to a dict suitable for JSON/CSV export."""
    d: dict = {f: getattr(record, f) for f in _RECORD_FIELDS}
    if parse_trigger_metadata and record.trigger_metadata:
        d["trigger_metadata"] = json.loads(record.trigger_metadata)
    return d


_AUTO_PRUNE_INTERVAL = 1000

_T = TypeVar("_T")


class AuditLogger:
    """Append-only audit logger backed by SQLite."""

    def __init__(
        self,
        db_path: Path | _LazyDbPath = DEFAULT_DB_PATH,
        *,
        auto_prune_interval: int = _AUTO_PRUNE_INTERVAL,
        retention_days: int = 90,
        max_records: int = 100_000,
    ) -> None:
        self._db_path = db_path
        self._insert_count = 0
        self._auto_prune_interval = auto_prune_interval
        self._retention_days = retention_days
        self._max_records = max_records
        resolved_path = Path(db_path) if not isinstance(db_path, Path) else db_path
        ensure_private_dir(resolved_path.parent)
        self._conn = sqlite3.connect(str(resolved_path), check_same_thread=False, timeout=30)
        try:
            secure_database(resolved_path)
            self._conn.row_factory = sqlite3.Row
            self._lock = threading.Lock()
            self._conn.execute("PRAGMA journal_mode=WAL;")
            self._conn.execute(_CREATE_TABLE)
            self._conn.execute(_CREATE_SECURITY_EVENTS_TABLE)
            self._conn.execute(_CREATE_DELEGATE_EVENTS_TABLE)
            _migrate_add_trigger_columns(self._conn)
            for idx in _CREATE_INDEXES:
                self._conn.execute(idx)
            for idx in _CREATE_SECURITY_INDEXES:
                self._conn.execute(idx)
            for idx in _CREATE_DELEGATE_INDEXES:
                self._conn.execute(idx)
            self._conn.commit()
        except Exception:
            self._conn.close()
            raise

    def _execute_insert_locked(
        self,
        sql: str,
        params: tuple,
        *,
        error_label: str,
        auto_prune: bool = True,
    ) -> None:
        """Execute an INSERT under lock with optional auto-prune. Never raises."""
        try:
            with self._lock:
                self._conn.execute(sql, params)
                self._conn.commit()
                if auto_prune:
                    self._insert_count += 1
                    if (
                        self._auto_prune_interval > 0
                        and self._insert_count % self._auto_prune_interval == 0
                    ):
                        self._prune_locked(
                            retention_days=self._retention_days,
                            max_records=self._max_records,
                        )
        except Exception as e:
            logger.error("Failed to write %s: %s", error_label, e)

    def log(self, record: AuditRecord) -> None:
        """Insert an audit record. Never raises — prints to stderr on failure."""
        user_prompt = scrub_secrets(record.user_prompt)
        output = scrub_secrets(record.output)
        error = scrub_secrets(record.error) if record.error else record.error
        self._execute_insert_locked(
            _INSERT,
            (
                record.run_id,
                record.agent_name,
                record.timestamp,
                user_prompt,
                record.model,
                record.provider,
                output,
                record.tokens_in,
                record.tokens_out,
                record.total_tokens,
                record.tool_calls,
                record.duration_ms,
                record.success,
                error,
                record.trigger_type,
                record.trigger_metadata,
            ),
            error_label="audit record",
        )

    def _query_table(
        self,
        table: str,
        filter_clauses: list[tuple[str, object | None]],
        limit: int,
        row_mapper: Callable[[sqlite3.Row], _T],
    ) -> list[_T]:
        """Generic filtered query on *table*. Skips clauses whose value is ``None``."""
        filters = [(clause, val) for clause, val in filter_clauses if val is not None]
        where, params = _build_where(filters)
        sql = f"SELECT * FROM {table} {where} ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [row_mapper(row) for row in rows]

    def query(
        self,
        *,
        agent_name: str | None = None,
        run_id: str | None = None,
        trigger_type: str | None = None,
        since: str | None = None,
        until: str | None = None,
        limit: int = 1000,
    ) -> list[AuditRecord]:
        """Query audit records with optional filters, ordered by timestamp DESC."""
        return self._query_table(
            "audit_log",
            [
                ("agent_name = ?", agent_name),
                ("run_id = ?", run_id),
                ("trigger_type = ?", trigger_type),
                ("timestamp >= ?", since),
                ("timestamp <= ?", until),
            ],
            limit,
            _row_to_record,
        )

    def log_security_event(
        self,
        event_type: str,
        agent_name: str,
        details: str,
        source_ip: str | None = None,
    ) -> None:
        """Log a security event. Never raises — prints to stderr on failure."""
        scrubbed_details = scrub_secrets(details)
        self._execute_insert_locked(
            _INSERT_SECURITY_EVENT,
            (
                datetime.now(UTC).isoformat(),
                event_type,
                agent_name,
                scrubbed_details,
                source_ip,
            ),
            error_label="security event",
            auto_prune=False,
        )

    def query_security_events(
        self,
        *,
        event_type: str | None = None,
        agent_name: str | None = None,
        limit: int = 1000,
    ) -> list[dict]:
        """Query security events with optional filters."""
        return self._query_table(
            "security_events",
            [
                ("event_type = ?", event_type),
                ("agent_name = ?", agent_name),
            ],
            limit,
            dict,
        )

    def log_delegate_event(
        self,
        *,
        source_service: str,
        target_service: str,
        status: str,
        source_run_id: str,
        reason: str | None = None,
        trace: str | None = None,
        payload_preview: str = "",
    ) -> None:
        """Log a delegate routing event. Never raises."""
        ts = datetime.now(UTC).isoformat()
        scrubbed_preview = scrub_secrets(payload_preview[:200])
        scrubbed_reason = scrub_secrets(reason) if reason else reason
        self._execute_insert_locked(
            _INSERT_DELEGATE_EVENT,
            (
                ts,
                source_service,
                target_service,
                status,
                source_run_id,
                scrubbed_reason,
                trace,
                scrubbed_preview,
            ),
            error_label="delegate event",
        )

    def query_delegate_events(
        self,
        *,
        source_service: str | None = None,
        target_service: str | None = None,
        status: str | None = None,
        source_run_id: str | None = None,
        since: str | None = None,
        until: str | None = None,
        limit: int = 1000,
    ) -> list[DelegateAuditEvent]:
        """Query delegate events with optional filters, ordered by timestamp DESC."""
        return self._query_table(
            "delegate_events",
            [
                ("source_service = ?", source_service),
                ("target_service = ?", target_service),
                ("status = ?", status),
                ("source_run_id = ?", source_run_id),
                ("timestamp >= ?", since),
                ("timestamp <= ?", until),
            ],
            limit,
            _row_to_delegate_event,
        )

    def _prune_locked(self, retention_days: int = 90, max_records: int = 100_000) -> int:
        """Core prune logic. Caller must hold self._lock."""
        deleted = 0
        try:
            from datetime import timedelta

            cutoff_dt = datetime.now(UTC) - timedelta(days=retention_days)
            cutoff = cutoff_dt.isoformat()

            cursor = self._conn.execute("DELETE FROM audit_log WHERE timestamp < ?", (cutoff,))
            deleted += cursor.rowcount

            # Also prune security_events and delegate_events
            self._conn.execute("DELETE FROM security_events WHERE timestamp < ?", (cutoff,))
            self._conn.execute("DELETE FROM delegate_events WHERE timestamp < ?", (cutoff,))

            # Trim to max_records (keep most recent)
            cursor = self._conn.execute(
                "DELETE FROM audit_log WHERE id NOT IN "
                "(SELECT id FROM audit_log ORDER BY timestamp DESC LIMIT ?)",
                (max_records,),
            )
            deleted += cursor.rowcount

            self._conn.commit()
        except Exception as e:
            logger.warning("Failed to prune records: %s", e)
        return deleted

    def prune(self, retention_days: int = 90, max_records: int = 100_000) -> int:
        """Delete old audit records and trim to max_records. Returns count deleted."""
        with self._lock:
            return self._prune_locked(retention_days, max_records)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def __enter__(self) -> AuditLogger:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()
