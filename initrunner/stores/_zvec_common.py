"""Shared zvec helpers used by both document and memory stores."""

from __future__ import annotations

import hashlib
import threading
from pathlib import Path

import zvec

from initrunner._log import get_logger
from initrunner.stores.base import DimensionMismatchError

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
# Common schemas and constants
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


# ---------------------------------------------------------------------------
# Meta collection helpers
# ---------------------------------------------------------------------------


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
    """Determine the effective dimensions for a store."""
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
