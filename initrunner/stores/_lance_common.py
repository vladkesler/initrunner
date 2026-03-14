"""Shared LanceDB helpers used by both document and memory stores."""

from __future__ import annotations

import hashlib
from pathlib import Path

import lancedb  # type: ignore[import-not-found]
import pyarrow as pa  # type: ignore[import-not-found]

from initrunner._log import get_logger
from initrunner.stores.base import DimensionMismatchError

logger = get_logger("memory")

# ---------------------------------------------------------------------------
# Meta table schema (key-value, no vector column)
# ---------------------------------------------------------------------------

_META_SCHEMA = pa.schema(
    [
        pa.field("key", pa.string()),
        pa.field("value", pa.string()),
    ]
)


# ---------------------------------------------------------------------------
# DB / meta helpers
# ---------------------------------------------------------------------------


def _open_db(path: Path) -> lancedb.DBConnection:
    """Open or create a LanceDB database directory."""
    return lancedb.connect(str(path))


def _table_names(db: lancedb.DBConnection) -> list[str]:
    """Return table names from the DB, handling both old and new API."""
    return db.list_tables().tables


def _ensure_meta_table(db: lancedb.DBConnection) -> None:
    """Create the ``_meta`` key-value table if it does not exist."""
    if "_meta" not in _table_names(db):
        db.create_table("_meta", schema=_META_SCHEMA)


def _read_meta(db: lancedb.DBConnection, key: str) -> str | None:
    """Read a value from the ``_meta`` table."""
    tbl = db.open_table("_meta")
    rows = tbl.search().where(f"key = '{_esc(key)}'", prefilter=True).limit(1).to_list()
    if rows:
        return rows[0]["value"]
    return None


def _write_meta(db: lancedb.DBConnection, key: str, value: str) -> None:
    """Write a key-value pair to the ``_meta`` table (upsert)."""
    tbl = db.open_table("_meta")
    tbl.merge_insert("key").when_matched_update_all().when_not_matched_insert_all().execute(
        [{"key": key, "value": value}]
    )


def _resolve_dimensions(
    db: lancedb.DBConnection,
    base_path: Path,
    passed: int | None,
    *,
    allow_none: bool = False,
) -> int | None:
    """Determine the effective dimensions for a store."""
    raw = _read_meta(db, "dimensions")
    stored = int(raw) if raw is not None else None

    if stored is not None and passed is not None and stored != passed:
        raise DimensionMismatchError(
            f"Store at {base_path} has {stored}d embeddings but {passed}d was requested. "
            "Re-ingest with --force or use a new store_path to switch models."
        )

    if stored is not None:
        return stored

    if passed is not None:
        _write_meta(db, "dimensions", str(passed))
        return passed

    if allow_none:
        return None

    raise DimensionMismatchError(
        f"Store at {base_path} has no recorded dimensions and none were provided. "
        "Pass dimensions explicitly or ingest documents first."
    )


def _esc(val: str) -> str:
    """Escape single quotes in SQL filter values."""
    return val.replace("'", "''")


def _safe_id(key: str) -> str:
    """Convert an arbitrary string (e.g. file path) to a valid ID."""
    return hashlib.sha256(key.encode()).hexdigest()
