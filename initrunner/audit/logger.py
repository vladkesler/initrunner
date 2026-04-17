"""Append-only SQLite audit log."""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypeVar

from initrunner._log import get_logger
from initrunner._paths import LazyPath, ensure_private_dir, secure_database
from initrunner.audit._hmac import (
    KeyInvalidError,
    KeyUnavailableError,
    canonical_serialize,
    compute_record_hash,
    load_hmac_key_readonly,
    load_or_create_hmac_key,
)
from initrunner.audit._redact import scrub_secrets

if TYPE_CHECKING:
    from initrunner.agent.executor import RunResult
    from initrunner.agent.schema.role import RoleDefinition

logger = get_logger("audit")


@dataclass(frozen=True)
class ChainVerifyResult:
    """Outcome of AuditLogger.verify_chain().

    `ok` is True iff no tampering was detected. `pruned_gaps` is purely
    informational: id gaps are expected when pruning ran and do not fail
    verification. `first_break_*` are only set when `ok` is False.

    Reason set for `first_break_reason`:
      - "hash_mismatch"                  record_hash != recomputed
      - "prev_hash_mismatch"             prev_hash != prior row's record_hash,
                                         with no id gap to explain it
      - "missing_hash_after_chain_start" NULL record_hash after a signed row
      - "key_missing"                    no env var and no key file
      - "key_invalid"                    env var/key file malformed
      - "query_error"                    SQLite error reading the chain
    """

    ok: bool
    total_rows: int
    unsigned_legacy_rows: int
    verified_rows: int
    last_verified_id: int | None
    last_verified_hash: str | None
    pruned_gaps: tuple[int, ...]
    first_break_id: int | None
    first_break_reason: str | None


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
    compose_name: str | None = None  # Compose project identity for filtering


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
    principal_id: str | None = None
    tool_names: str | None = None  # JSON-encoded list of tool names

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
        principal_id: str | None = None,
    ) -> AuditRecord:
        """Build an AuditRecord from a RunResult and role definition."""
        return cls(
            run_id=result.run_id,
            agent_name=role.metadata.name,
            timestamp=datetime.now(UTC).isoformat(),
            user_prompt=prompt,
            model=role.spec.model.name,  # type: ignore[union-attr]
            provider=role.spec.model.provider,  # type: ignore[union-attr]
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
            principal_id=principal_id,
            tool_names=json.dumps(result.tool_call_names) if result.tool_call_names else None,
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
    duration_ms, success, error, trigger_type, trigger_metadata,
    principal_id, tool_names, prev_hash, record_hash
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
"""

_SELECT_CHAIN_TIP = """\
SELECT record_hash FROM audit_log
WHERE record_hash IS NOT NULL
ORDER BY id DESC LIMIT 1;
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
INSERT INTO security_events (timestamp, event_type, agent_name, details, source_ip, principal_id)
VALUES (?, ?, ?, ?, ?, ?);
"""

_CREATE_BUDGET_STATE_TABLE = """\
CREATE TABLE IF NOT EXISTS budget_state (
    agent_name TEXT PRIMARY KEY,
    total_consumed INTEGER NOT NULL DEFAULT 0,
    daily_consumed INTEGER NOT NULL DEFAULT 0,
    daily_cost_consumed REAL NOT NULL DEFAULT 0.0,
    weekly_cost_consumed REAL NOT NULL DEFAULT 0.0,
    last_reset_date TEXT NOT NULL,
    last_weekly_reset TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""

_UPSERT_BUDGET_STATE = """\
INSERT OR REPLACE INTO budget_state (
    agent_name, total_consumed, daily_consumed, daily_cost_consumed,
    weekly_cost_consumed, last_reset_date, last_weekly_reset, updated_at
) VALUES (?, ?, ?, ?, ?, ?, ?, ?);
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
    payload_preview TEXT NOT NULL,
    compose_name TEXT
);
"""

_CREATE_DELEGATE_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_del_source ON delegate_events (source_service);",
    "CREATE INDEX IF NOT EXISTS idx_del_target ON delegate_events (target_service);",
    "CREATE INDEX IF NOT EXISTS idx_del_status ON delegate_events (status);",
    "CREATE INDEX IF NOT EXISTS idx_del_timestamp ON delegate_events (timestamp);",
    "CREATE INDEX IF NOT EXISTS idx_del_run_id ON delegate_events (source_run_id);",
    "CREATE INDEX IF NOT EXISTS idx_del_compose ON delegate_events (compose_name);",
]

_INSERT_DELEGATE_EVENT = """\
INSERT INTO delegate_events (
    timestamp, source_service, target_service, status,
    source_run_id, reason, trace, payload_preview, compose_name
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
"""


def _default_db_path() -> Path:
    from initrunner.config import get_audit_db_path

    return get_audit_db_path()


class _LazyDbPath(LazyPath):
    """Lazy-evaluated default DB path to avoid import-time filesystem access."""

    _value: Path | None = None

    def _resolve(self) -> Path:
        if self._value is None:
            self._value = _default_db_path()
        return self._value


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


def _migrate_add_principal_column(conn: sqlite3.Connection) -> None:
    """Idempotent migration: add principal_id column to existing DBs."""
    try:
        conn.execute("ALTER TABLE audit_log ADD COLUMN principal_id TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE security_events ADD COLUMN principal_id TEXT")
    except sqlite3.OperationalError:
        pass


def _migrate_add_compose_name_column(conn: sqlite3.Connection) -> None:
    """Idempotent migration: add compose_name to delegate_events."""
    try:
        conn.execute("ALTER TABLE delegate_events ADD COLUMN compose_name TEXT")
    except sqlite3.OperationalError:
        pass  # Column already exists


def _migrate_add_tool_names_column(conn: sqlite3.Connection) -> None:
    """Idempotent migration: add tool_names JSON column to audit_log."""
    try:
        conn.execute("ALTER TABLE audit_log ADD COLUMN tool_names TEXT")
    except sqlite3.OperationalError:
        pass  # Column already exists


def _migrate_add_hash_columns(conn: sqlite3.Connection) -> None:
    """Idempotent migration: add prev_hash/record_hash columns for the signed chain.

    Both columns are nullable TEXT; rows predating this migration keep NULL and
    are reported as legacy by verify_chain().
    """
    for col in ("prev_hash", "record_hash"):
        try:
            conn.execute(f"ALTER TABLE audit_log ADD COLUMN {col} TEXT")
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
    # compose_name may be absent in pre-migration rows
    try:
        compose_name = row["compose_name"]
    except (IndexError, KeyError):
        compose_name = None
    return DelegateAuditEvent(
        timestamp=row["timestamp"],
        source_service=row["source_service"],
        target_service=row["target_service"],
        status=row["status"],
        source_run_id=row["source_run_id"],
        reason=row["reason"],
        trace=row["trace"],
        payload_preview=row["payload_preview"],
        compose_name=compose_name,
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
        principal_id=row["principal_id"],
        tool_names=row["tool_names"],
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
    "principal_id",
    "tool_names",
]


def record_to_dict(record: AuditRecord, *, parse_trigger_metadata: bool = False) -> dict[str, Any]:
    """Convert an AuditRecord to a dict suitable for JSON/CSV export."""
    d: dict[str, Any] = {f: getattr(record, f) for f in _RECORD_FIELDS}
    if parse_trigger_metadata and record.trigger_metadata:
        d["trigger_metadata"] = json.loads(record.trigger_metadata)
    return d


_AUTO_PRUNE_INTERVAL = 1000

_ALLOWED_TABLES: frozenset[str] = frozenset({"audit_log", "security_events", "delegate_events"})

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
        self._hmac_key: bytes | None = None  # loaded lazily on first log()
        resolved_path = Path(db_path) if not isinstance(db_path, Path) else db_path
        ensure_private_dir(resolved_path.parent)
        self._conn = sqlite3.connect(
            str(resolved_path),
            check_same_thread=False,
            timeout=30,
            isolation_level=None,  # autocommit; signing path opens BEGIN IMMEDIATE explicitly
        )
        try:
            secure_database(resolved_path)
            self._conn.row_factory = sqlite3.Row
            self._lock = threading.Lock()
            self._conn.execute("PRAGMA journal_mode=WAL;")
            self._conn.execute(_CREATE_TABLE)
            self._conn.execute(_CREATE_SECURITY_EVENTS_TABLE)
            self._conn.execute(_CREATE_DELEGATE_EVENTS_TABLE)
            self._conn.execute(_CREATE_BUDGET_STATE_TABLE)
            _migrate_add_trigger_columns(self._conn)
            _migrate_add_principal_column(self._conn)
            _migrate_add_compose_name_column(self._conn)
            _migrate_add_tool_names_column(self._conn)
            _migrate_add_hash_columns(self._conn)
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

    def _get_hmac_key(self) -> bytes:
        """Return the cached HMAC key, loading/creating it on first call."""
        if self._hmac_key is None:
            self._hmac_key = load_or_create_hmac_key()
        return self._hmac_key

    def _log_signed_locked(self, record: AuditRecord) -> None:
        """Sign and insert one audit record inside a BEGIN IMMEDIATE transaction.

        Acquires `self._lock` AND a SQLite write lock (BEGIN IMMEDIATE) so
        concurrent processes on the same DB cannot fork the chain.
        """
        scrubbed = AuditRecord(
            run_id=record.run_id,
            agent_name=record.agent_name,
            timestamp=record.timestamp,
            user_prompt=scrub_secrets(record.user_prompt),
            model=record.model,
            provider=record.provider,
            output=scrub_secrets(record.output),
            tokens_in=record.tokens_in,
            tokens_out=record.tokens_out,
            total_tokens=record.total_tokens,
            tool_calls=record.tool_calls,
            duration_ms=record.duration_ms,
            success=record.success,
            error=scrub_secrets(record.error) if record.error else record.error,
            trigger_type=record.trigger_type,
            trigger_metadata=record.trigger_metadata,
            principal_id=record.principal_id,
            tool_names=record.tool_names,
        )
        key = self._get_hmac_key()
        record_dict = {f: getattr(scrubbed, f) for f in _RECORD_FIELDS}
        serialized = canonical_serialize(record_dict, _RECORD_FIELDS)

        with self._lock:
            in_txn = False
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                in_txn = True
                prev_row = self._conn.execute(_SELECT_CHAIN_TIP).fetchone()
                prev_hash = prev_row["record_hash"] if prev_row else None
                record_hash = compute_record_hash(key, prev_hash, serialized)
                self._conn.execute(
                    _INSERT,
                    (
                        scrubbed.run_id,
                        scrubbed.agent_name,
                        scrubbed.timestamp,
                        scrubbed.user_prompt,
                        scrubbed.model,
                        scrubbed.provider,
                        scrubbed.output,
                        scrubbed.tokens_in,
                        scrubbed.tokens_out,
                        scrubbed.total_tokens,
                        scrubbed.tool_calls,
                        scrubbed.duration_ms,
                        scrubbed.success,
                        scrubbed.error,
                        scrubbed.trigger_type,
                        scrubbed.trigger_metadata,
                        scrubbed.principal_id,
                        scrubbed.tool_names,
                        prev_hash,
                        record_hash,
                    ),
                )
                self._conn.commit()
                in_txn = False
                self._insert_count += 1
                if (
                    self._auto_prune_interval > 0
                    and self._insert_count % self._auto_prune_interval == 0
                ):
                    self._prune_locked(
                        retention_days=self._retention_days,
                        max_records=self._max_records,
                    )
            except Exception:
                if in_txn:
                    try:
                        self._conn.rollback()
                    except Exception:
                        pass
                raise

    def log(self, record: AuditRecord) -> None:
        """Insert a signed audit record. Never raises — logs on failure."""
        try:
            self._log_signed_locked(record)
        except Exception as e:
            logger.error("Failed to write audit record: %s", e)

    # -- budget state persistence --------------------------------------------

    def save_budget_state(self, agent_name: str, state: dict) -> None:
        """Persist daemon budget counters. Never raises."""
        from datetime import UTC, datetime

        self._execute_insert_locked(
            _UPSERT_BUDGET_STATE,
            (
                agent_name,
                state["total_consumed"],
                state["daily_consumed"],
                state["daily_cost_consumed"],
                state["weekly_cost_consumed"],
                state["last_reset_date"],
                state["last_weekly_reset"],
                datetime.now(UTC).isoformat(),
            ),
            error_label="budget state",
            auto_prune=False,
        )

    def load_budget_state(self, agent_name: str) -> dict | None:
        """Load persisted budget counters. Returns None if missing or on error."""
        try:
            with self._lock:
                row = self._conn.execute(
                    "SELECT * FROM budget_state WHERE agent_name = ?",
                    (agent_name,),
                ).fetchone()
            if row is None:
                return None
            return {
                "total_consumed": row["total_consumed"],
                "daily_consumed": row["daily_consumed"],
                "daily_cost_consumed": row["daily_cost_consumed"],
                "weekly_cost_consumed": row["weekly_cost_consumed"],
                "last_reset_date": row["last_reset_date"],
                "last_weekly_reset": row["last_weekly_reset"],
            }
        except Exception as e:
            logger.error("Failed to load budget state for %s: %s", agent_name, e)
            return None

    def _query_table(
        self,
        table: str,
        filter_clauses: list[tuple[str, object | None]],
        limit: int,
        row_mapper: Callable[[sqlite3.Row], _T],
    ) -> list[_T]:
        """Generic filtered query on *table*. Skips clauses whose value is ``None``."""
        if table not in _ALLOWED_TABLES:
            raise ValueError(f"Unknown audit table: {table!r}")
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
        principal_id: str | None = None,
        since: str | None = None,
        until: str | None = None,
        limit: int = 1000,
        exclude_trigger_types: list[str] | None = None,
    ) -> list[AuditRecord]:
        """Query audit records with optional filters, ordered by timestamp DESC."""
        filter_clauses: list[tuple[str, object | None]] = [
            ("agent_name = ?", agent_name),
            ("run_id = ?", run_id),
            ("trigger_type = ?", trigger_type),
            ("principal_id = ?", principal_id),
            ("timestamp >= ?", since),
            ("timestamp <= ?", until),
        ]
        filters: list[tuple[str, object]] = [
            (clause, val) for clause, val in filter_clauses if val is not None
        ]
        where, params = _build_where(filters)

        # Exclusion filter for internal trigger types (applied before LIMIT)
        if exclude_trigger_types:
            placeholders = ", ".join("?" for _ in exclude_trigger_types)
            excl_clause = f"(trigger_type IS NULL OR trigger_type NOT IN ({placeholders}))"
            if where:
                where += f" AND {excl_clause}"
            else:
                where = f"WHERE {excl_clause}"
            params.extend(exclude_trigger_types)

        sql = f"SELECT * FROM audit_log {where} ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [_row_to_record(row) for row in rows]

    def log_security_event(
        self,
        event_type: str,
        agent_name: str,
        details: str,
        source_ip: str | None = None,
        principal_id: str | None = None,
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
                principal_id,
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
        compose_name: str | None = None,
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
                compose_name,
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
        compose_name: str | None = None,
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
                ("compose_name = ?", compose_name),
                ("timestamp >= ?", since),
                ("timestamp <= ?", until),
            ],
            limit,
            _row_to_delegate_event,
        )

    def stats(
        self,
        *,
        agent_name: str | None = None,
        since: str | None = None,
        until: str | None = None,
    ):
        """Compute aggregate stats from the audit_log table."""
        from initrunner.services.operations import AuditStats, TopAgent

        filters: list[tuple[str, object | None]] = [
            ("agent_name = ?", agent_name),
            ("timestamp >= ?", since),
            ("timestamp <= ?", until),
        ]
        active = [(c, v) for c, v in filters if v is not None]
        where, params = _build_where(active)

        sql = f"""
            SELECT
                COUNT(*) AS total_runs,
                COALESCE(SUM(CASE WHEN success THEN 1 ELSE 0 END), 0) AS successes,
                COALESCE(SUM(total_tokens), 0) AS total_tokens,
                COALESCE(AVG(duration_ms), 0) AS avg_duration_ms
            FROM audit_log {where}
        """
        top_sql = f"""
            SELECT agent_name, COUNT(*) AS cnt, COALESCE(AVG(duration_ms), 0) AS avg_dur
            FROM audit_log {where}
            GROUP BY agent_name ORDER BY cnt DESC LIMIT 5
        """

        with self._lock:
            row = self._conn.execute(sql, params).fetchone()
            top_rows = self._conn.execute(top_sql, params).fetchall()

        total = row["total_runs"] if row else 0
        successes = row["successes"] if row else 0
        rate = (successes / total * 100.0) if total > 0 else 0.0

        top_agents = [
            TopAgent(name=r["agent_name"], count=r["cnt"], avg_duration_ms=int(r["avg_dur"]))
            for r in top_rows
        ]

        return AuditStats(
            total_runs=total,
            success_rate=round(rate, 1),
            total_tokens=row["total_tokens"] if row else 0,
            avg_duration_ms=int(row["avg_duration_ms"]) if row else 0,
            top_agents=top_agents,
        )

    def trigger_stats(self, *, agent_name: str) -> list:
        """Per-trigger-type stats for an agent. Returns list[TriggerStat]."""
        from initrunner.services.operations import TriggerStat

        agg_sql = """\
            SELECT
                trigger_type,
                COUNT(*) AS fire_count,
                SUM(CASE WHEN success THEN 1 ELSE 0 END) AS success_count,
                SUM(CASE WHEN NOT success THEN 1 ELSE 0 END) AS fail_count,
                MAX(timestamp) AS last_fire_time,
                CAST(AVG(duration_ms) AS INTEGER) AS avg_duration_ms
            FROM audit_log
            WHERE agent_name = ? AND trigger_type IS NOT NULL
            GROUP BY trigger_type
        """
        error_sql = """\
            SELECT error FROM audit_log
            WHERE agent_name = ? AND trigger_type = ? AND success = 0 AND error IS NOT NULL
            ORDER BY timestamp DESC LIMIT 1
        """

        with self._lock:
            rows = self._conn.execute(agg_sql, (agent_name,)).fetchall()
            results: list[TriggerStat] = []
            for row in rows:
                ttype = row["trigger_type"]
                last_error: str | None = None
                if row["fail_count"] > 0:
                    err_row = self._conn.execute(error_sql, (agent_name, ttype)).fetchone()
                    if err_row:
                        last_error = err_row["error"]
                results.append(
                    TriggerStat(
                        trigger_type=ttype,
                        fire_count=row["fire_count"],
                        success_count=row["success_count"],
                        fail_count=row["fail_count"],
                        last_fire_time=row["last_fire_time"],
                        avg_duration_ms=int(row["avg_duration_ms"]),
                        last_error=last_error,
                    )
                )
        return results

    def timeline_query(
        self,
        *,
        agent_name: str,
        since: str,
        until: str,
        trigger_type: str | None = None,
        limit: int = 500,
    ) -> list[dict]:
        """Lightweight timeline entries for Gantt rendering, ordered ASC."""
        if trigger_type is not None:
            sql = """\
                SELECT run_id, agent_name, timestamp, duration_ms,
                       success, error, trigger_type, trigger_metadata,
                       tokens_in, tokens_out, total_tokens, tool_calls,
                       model, provider
                FROM audit_log
                WHERE agent_name = ? AND trigger_type = ?
                      AND timestamp >= ? AND timestamp <= ?
                ORDER BY timestamp ASC LIMIT ?
            """
            params = (agent_name, trigger_type, since, until, limit)
        else:
            sql = """\
                SELECT run_id, agent_name, timestamp, duration_ms,
                       success, error, trigger_type, trigger_metadata,
                       tokens_in, tokens_out, total_tokens, tool_calls,
                       model, provider
                FROM audit_log
                WHERE agent_name = ? AND timestamp >= ? AND timestamp <= ?
                ORDER BY timestamp ASC LIMIT ?
            """
            params = (agent_name, since, until, limit)
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def timeline_stats(
        self,
        *,
        agent_name: str,
        since: str,
        until: str,
        trigger_type: str | None = None,
    ) -> dict:
        """Aggregate stats for the timeline view."""
        if trigger_type is not None:
            sql = """\
                SELECT
                    COUNT(*) AS total_runs,
                    COALESCE(SUM(CASE WHEN success THEN 1 ELSE 0 END), 0) AS success_count,
                    COALESCE(SUM(CASE WHEN NOT success THEN 1 ELSE 0 END), 0) AS error_count,
                    COALESCE(SUM(total_tokens), 0) AS total_tokens,
                    COALESCE(AVG(duration_ms), 0) AS avg_duration_ms,
                    COALESCE(MAX(duration_ms), 0) AS max_duration_ms
                FROM audit_log
                WHERE agent_name = ? AND trigger_type = ?
                      AND timestamp >= ? AND timestamp <= ?
            """
            params = (agent_name, trigger_type, since, until)
        else:
            sql = """\
                SELECT
                    COUNT(*) AS total_runs,
                    COALESCE(SUM(CASE WHEN success THEN 1 ELSE 0 END), 0) AS success_count,
                    COALESCE(SUM(CASE WHEN NOT success THEN 1 ELSE 0 END), 0) AS error_count,
                    COALESCE(SUM(total_tokens), 0) AS total_tokens,
                    COALESCE(AVG(duration_ms), 0) AS avg_duration_ms,
                    COALESCE(MAX(duration_ms), 0) AS max_duration_ms
                FROM audit_log
                WHERE agent_name = ? AND timestamp >= ? AND timestamp <= ?
            """
            params = (agent_name, since, until)
        with self._lock:
            row = self._conn.execute(sql, params).fetchone()
        if not row or row["total_runs"] == 0:
            return {
                "total_runs": 0,
                "success_count": 0,
                "error_count": 0,
                "success_rate": 0.0,
                "total_tokens": 0,
                "avg_duration_ms": 0,
                "max_duration_ms": 0,
            }
        total = row["total_runs"]
        return {
            "total_runs": total,
            "success_count": row["success_count"],
            "error_count": row["error_count"],
            "success_rate": round(row["success_count"] / total * 100.0, 1),
            "total_tokens": row["total_tokens"],
            "avg_duration_ms": int(row["avg_duration_ms"]),
            "max_duration_ms": row["max_duration_ms"],
        }

    # ------------------------------------------------------------------
    # Cost aggregate queries
    # ------------------------------------------------------------------

    def _cost_filters(
        self,
        agent_name: str | None,
        since: str | None,
        until: str | None,
    ) -> tuple[str, list[object]]:
        filters: list[tuple[str, object]] = [
            (clause, val)
            for clause, val in [
                ("agent_name = ?", agent_name),
                ("timestamp >= ?", since),
                ("timestamp <= ?", until),
            ]
            if val is not None
        ]
        return _build_where(filters)

    def cost_by_agent(
        self,
        *,
        agent_name: str | None = None,
        since: str | None = None,
        until: str | None = None,
    ) -> list[dict]:
        """Aggregate token usage grouped by agent, model, and provider.

        Ordered by total token volume descending (proxy for cost).
        """
        where, params = self._cost_filters(agent_name, since, until)
        sql = f"""\
            SELECT agent_name, model, provider,
                   COALESCE(SUM(tokens_in), 0)  AS tokens_in,
                   COALESCE(SUM(tokens_out), 0) AS tokens_out,
                   COUNT(*)                      AS run_count
            FROM audit_log {where}
            GROUP BY agent_name, model, provider
            ORDER BY SUM(tokens_in + tokens_out) DESC
        """
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def cost_by_day(
        self,
        *,
        agent_name: str | None = None,
        since: str | None = None,
        until: str | None = None,
    ) -> list[dict]:
        """Aggregate token usage grouped by calendar day, model, and provider.

        Ordered by date ascending.
        """
        where, params = self._cost_filters(agent_name, since, until)
        sql = f"""\
            SELECT date(timestamp) AS date, model, provider,
                   COALESCE(SUM(tokens_in), 0)  AS tokens_in,
                   COALESCE(SUM(tokens_out), 0) AS tokens_out,
                   COUNT(*)                      AS run_count
            FROM audit_log {where}
            GROUP BY date(timestamp), model, provider
            ORDER BY date(timestamp) ASC
        """
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def cost_by_model(
        self,
        *,
        since: str | None = None,
        until: str | None = None,
    ) -> list[dict]:
        """Aggregate token usage grouped by model and provider.

        Ordered by total token volume descending.
        """
        where, params = self._cost_filters(None, since, until)
        sql = f"""\
            SELECT model, provider,
                   COALESCE(SUM(tokens_in), 0)  AS tokens_in,
                   COALESCE(SUM(tokens_out), 0) AS tokens_out,
                   COUNT(*)                      AS run_count
            FROM audit_log {where}
            GROUP BY model, provider
            ORDER BY SUM(tokens_in + tokens_out) DESC
        """
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def cost_by_tool(
        self,
        *,
        agent_name: str | None = None,
        since: str | None = None,
        until: str | None = None,
    ) -> list[dict]:
        """Aggregate token usage grouped by individual tool name.

        Uses a CTE to avoid overcounting: if a tool appears N times in one
        run, ``usage_count`` reflects N but token totals are counted once
        per (run, tool) pair.
        """
        where, params = self._cost_filters(agent_name, since, until)
        extra = "a.tool_names IS NOT NULL"
        if where:
            where += f" AND {extra}"
        else:
            where = f"WHERE {extra}"

        sql = f"""\
            WITH tool_runs AS (
                SELECT DISTINCT a.run_id, je.value AS tool_name,
                       a.tokens_in, a.tokens_out, a.model, a.provider,
                       COUNT(*) OVER (PARTITION BY a.run_id, je.value) AS call_count
                FROM audit_log a, json_each(a.tool_names) je
                {where}
            )
            SELECT tool_name,
                   COALESCE(SUM(call_count), 0) AS usage_count,
                   COUNT(*)                      AS run_count,
                   COALESCE(SUM(tokens_in), 0)  AS tokens_in,
                   COALESCE(SUM(tokens_out), 0) AS tokens_out,
                   model, provider
            FROM tool_runs
            GROUP BY tool_name, model, provider
            ORDER BY usage_count DESC
        """
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def verify_chain(self) -> ChainVerifyResult:
        """Walk the signed chain and verify every signed row. Never raises.

        Legacy rows (NULL hashes) before the first signed row are tolerated.
        A NULL hash after the chain has started is a break. id gaps with a
        matching prev_hash mismatch are treated as pruning (informational).
        """
        try:
            key = load_hmac_key_readonly()
        except KeyUnavailableError:
            return ChainVerifyResult(
                ok=False,
                total_rows=0,
                unsigned_legacy_rows=0,
                verified_rows=0,
                last_verified_id=None,
                last_verified_hash=None,
                pruned_gaps=(),
                first_break_id=None,
                first_break_reason="key_missing",
            )
        except KeyInvalidError:
            return ChainVerifyResult(
                ok=False,
                total_rows=0,
                unsigned_legacy_rows=0,
                verified_rows=0,
                last_verified_id=None,
                last_verified_hash=None,
                pruned_gaps=(),
                first_break_id=None,
                first_break_reason="key_invalid",
            )

        select_cols = ", ".join(("id", *_RECORD_FIELDS, "prev_hash", "record_hash"))
        sql = f"SELECT {select_cols} FROM audit_log ORDER BY id ASC"

        total_rows = 0
        legacy_rows = 0
        verified_rows = 0
        last_id: int | None = None
        last_hash: str | None = None
        pruned_gaps: list[int] = []
        chain_started = False
        expected_prev_hash: str | None = None
        prev_row_id: int | None = None

        with self._lock:
            try:
                cursor = self._conn.execute(sql)
            except sqlite3.Error:
                return ChainVerifyResult(
                    ok=False,
                    total_rows=0,
                    unsigned_legacy_rows=0,
                    verified_rows=0,
                    last_verified_id=None,
                    last_verified_hash=None,
                    pruned_gaps=(),
                    first_break_id=None,
                    first_break_reason="query_error",
                )

            while True:
                try:
                    batch = cursor.fetchmany(500)
                except sqlite3.Error:
                    return ChainVerifyResult(
                        ok=False,
                        total_rows=total_rows,
                        unsigned_legacy_rows=legacy_rows,
                        verified_rows=verified_rows,
                        last_verified_id=last_id,
                        last_verified_hash=last_hash,
                        pruned_gaps=tuple(pruned_gaps),
                        first_break_id=None,
                        first_break_reason="query_error",
                    )
                if not batch:
                    break

                for row in batch:
                    total_rows += 1
                    stored_record_hash = row["record_hash"]
                    stored_prev_hash = row["prev_hash"]
                    row_id = row["id"]

                    if stored_record_hash is None:
                        if chain_started:
                            return ChainVerifyResult(
                                ok=False,
                                total_rows=total_rows,
                                unsigned_legacy_rows=legacy_rows,
                                verified_rows=verified_rows,
                                last_verified_id=last_id,
                                last_verified_hash=last_hash,
                                pruned_gaps=tuple(pruned_gaps),
                                first_break_id=row_id,
                                first_break_reason="missing_hash_after_chain_start",
                            )
                        legacy_rows += 1
                        prev_row_id = row_id
                        continue

                    if not chain_started:
                        chain_started = True
                        expected_prev_hash = stored_prev_hash

                    id_gap = prev_row_id is not None and row_id != prev_row_id + 1
                    if stored_prev_hash != expected_prev_hash:
                        if id_gap:
                            pruned_gaps.append(row_id)
                            expected_prev_hash = stored_prev_hash
                        else:
                            return ChainVerifyResult(
                                ok=False,
                                total_rows=total_rows,
                                unsigned_legacy_rows=legacy_rows,
                                verified_rows=verified_rows,
                                last_verified_id=last_id,
                                last_verified_hash=last_hash,
                                pruned_gaps=tuple(pruned_gaps),
                                first_break_id=row_id,
                                first_break_reason="prev_hash_mismatch",
                            )

                    record_dict = {f: row[f] for f in _RECORD_FIELDS}
                    record_dict["success"] = bool(record_dict["success"])
                    serialized = canonical_serialize(record_dict, _RECORD_FIELDS)
                    expected_hash = compute_record_hash(key, expected_prev_hash, serialized)
                    if expected_hash != stored_record_hash:
                        return ChainVerifyResult(
                            ok=False,
                            total_rows=total_rows,
                            unsigned_legacy_rows=legacy_rows,
                            verified_rows=verified_rows,
                            last_verified_id=last_id,
                            last_verified_hash=last_hash,
                            pruned_gaps=tuple(pruned_gaps),
                            first_break_id=row_id,
                            first_break_reason="hash_mismatch",
                        )

                    verified_rows += 1
                    last_id = row_id
                    last_hash = stored_record_hash
                    expected_prev_hash = stored_record_hash
                    prev_row_id = row_id

        return ChainVerifyResult(
            ok=True,
            total_rows=total_rows,
            unsigned_legacy_rows=legacy_rows,
            verified_rows=verified_rows,
            last_verified_id=last_id,
            last_verified_hash=last_hash,
            pruned_gaps=tuple(pruned_gaps),
            first_break_id=None,
            first_break_reason=None,
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

            # Trim to max_records (keep most recent by insertion order).
            # Using `id DESC` rather than `timestamp DESC` so the tail of the
            # hash chain is preserved even if rows have out-of-order timestamps.
            cursor = self._conn.execute(
                "DELETE FROM audit_log WHERE id NOT IN "
                "(SELECT id FROM audit_log ORDER BY id DESC LIMIT ?)",
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
