"""HMAC key management and canonical serialisation for the signed audit chain.

The key lives at `~/.initrunner/audit_hmac.key` (0600, 32 random bytes),
auto-generated on first signing use. `INITRUNNER_AUDIT_HMAC_KEY` env var
overrides the file for CI and cross-host verification; it must be hex-encoded.

This module has no dependency on `logger.py` and takes records as
`Mapping[str, Any]` to avoid a circular import.
"""

from __future__ import annotations

import binascii
import hmac
import json
import os
import secrets
from collections.abc import Mapping, Sequence
from hashlib import sha256
from pathlib import Path

from initrunner.config import get_audit_hmac_key_path

_ENV_VAR = "INITRUNNER_AUDIT_HMAC_KEY"
_KEY_BYTES = 32


class KeyUnavailableError(RuntimeError):
    """No env var set and no key file exists."""


class KeyInvalidError(ValueError):
    """Env var value is not valid hex, or key file has wrong length."""


def _load_from_env() -> bytes | None:
    raw = os.environ.get(_ENV_VAR)
    if not raw:
        return None
    try:
        key = binascii.unhexlify(raw.strip())
    except (binascii.Error, ValueError) as e:
        raise KeyInvalidError(f"{_ENV_VAR} is not valid hex: {e}") from e
    if len(key) != _KEY_BYTES:
        raise KeyInvalidError(f"{_ENV_VAR} must decode to {_KEY_BYTES} bytes, got {len(key)}")
    return key


def _read_key_file(path: Path) -> bytes | None:
    if not path.exists():
        return None
    key = path.read_bytes()
    if len(key) != _KEY_BYTES:
        raise KeyInvalidError(f"Key file {path} has {len(key)} bytes, expected {_KEY_BYTES}")
    return key


def _atomic_place_key(path: Path, key: bytes) -> bytes:
    """Place `key` at `path` atomically if absent, else return the existing key.

    Writes `key` to a sibling tempfile, then `os.link`s it into place.
    `os.link` fails if the target exists, so concurrent writers (same-process
    threads or cross-process) deterministically see one winner; losers read
    the winner's key back and discard their own tempfile.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.parent / f".{path.name}.tmp.{os.getpid()}.{secrets.token_hex(4)}"
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(fd, key)
        os.fsync(fd)
    finally:
        os.close(fd)
    try:
        os.link(str(tmp), str(path))
    except FileExistsError:
        existing = _read_key_file(path)
        if existing is None:
            raise
        return existing
    finally:
        try:
            os.unlink(str(tmp))
        except OSError:
            pass
    return key


def load_or_create_hmac_key(path: Path | None = None) -> bytes:
    """Signing path. Env var wins; else read file; else generate+write.

    Concurrency: if two callers race to create the file, the loser of the
    O_EXCL race reads the winner's key back instead of raising.
    """
    env_key = _load_from_env()
    if env_key is not None:
        return env_key
    key_path = path or get_audit_hmac_key_path()
    existing = _read_key_file(key_path)
    if existing is not None:
        return existing
    new_key = secrets.token_bytes(_KEY_BYTES)
    return _atomic_place_key(key_path, new_key)


def load_hmac_key_readonly(path: Path | None = None) -> bytes:
    """Verification path. Env var wins; else read file. Never creates a key."""
    env_key = _load_from_env()
    if env_key is not None:
        return env_key
    key_path = path or get_audit_hmac_key_path()
    existing = _read_key_file(key_path)
    if existing is None:
        raise KeyUnavailableError(f"No key at {key_path} and {_ENV_VAR} not set")
    return existing


def canonical_serialize(record: Mapping[str, object], fields: Sequence[str]) -> bytes:
    """Deterministic JSON for the signed field subset.

    No `default=` fallback: a non-JSON-serialisable value raises TypeError so
    the drift is caught at sign time, not silently coerced.
    `ensure_ascii=True` means the bytes are identical regardless of locale
    or platform; every non-ASCII char becomes a \\uXXXX escape.
    """
    subset = {f: record[f] for f in fields if f in record}
    return json.dumps(subset, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(
        "ascii"
    )


def compute_record_hash(key: bytes, prev_hash: str | None, serialized: bytes) -> str:
    """HMAC-SHA256(key, prev_hash_ascii || serialized), hex-encoded."""
    prev_bytes = (prev_hash or "").encode("ascii")
    return hmac.new(key, prev_bytes + serialized, sha256).hexdigest()
