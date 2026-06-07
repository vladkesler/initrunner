"""Telemetry consent state: an anonymous install id plus an opt-out flag.

State lives at ``~/.initrunner/telemetry.json`` (mode 0600). It is created
silently on first use, like ``audit_hmac.key`` (see ``audit/_hmac.py``), and
every function here is best-effort: failures are logged at debug and never
raised to callers.
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import uuid
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel

from initrunner.config import get_telemetry_config_path

_logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1

_DO_NOT_TRACK = "DO_NOT_TRACK"
_INITRUNNER_TELEMETRY = "INITRUNNER_TELEMETRY"

_OFF_VALUES = frozenset({"0", "false", "off", "no", "disable", "disabled"})
_ON_VALUES = frozenset({"1", "true", "on", "yes", "enable", "enabled"})


class TelemetryState(BaseModel):
    """Persisted telemetry consent record."""

    schema_version: int = SCHEMA_VERSION
    install_id: str = ""
    enabled: bool = True
    notice_shown: bool = False
    created_at: str = ""


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


# ---------------------------------------------------------------------------
# Read / write
# ---------------------------------------------------------------------------


def _load_raw() -> TelemetryState | None:
    """Return the persisted state, or ``None`` if absent/unreadable. Never raises."""
    try:
        path = get_telemetry_config_path()
        if not path.is_file():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return None
        return TelemetryState.model_validate(data)
    except Exception:
        _logger.debug("Failed to load telemetry state", exc_info=True)
        return None


def _atomic_create(path: Path, state: TelemetryState) -> TelemetryState:
    """Create the file atomically if absent; if a concurrent writer won, return theirs.

    Mirrors ``audit/_hmac.py::_atomic_place_key``: write to a sibling tempfile,
    then ``os.link`` it into place. ``os.link`` fails if the target exists, so
    racing first-runs deterministically agree on one ``install_id``.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = state.model_dump_json().encode("utf-8")
    tmp = path.parent / f".{path.name}.tmp.{os.getpid()}.{secrets.token_hex(4)}"
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(fd, payload)
        os.fsync(fd)
    finally:
        os.close(fd)
    try:
        os.link(str(tmp), str(path))
    except FileExistsError:
        existing = _load_raw()
        if existing is not None:
            return existing
        os.replace(str(tmp), str(path))
        return state
    finally:
        try:
            os.unlink(str(tmp))
        except OSError:
            pass
    return state


def _atomic_write(path: Path, state: TelemetryState) -> None:
    """Replace the file atomically (temp + fsync + ``os.replace``) at mode 0600."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = state.model_dump_json().encode("utf-8")
    tmp = path.parent / f".{path.name}.tmp.{os.getpid()}.{secrets.token_hex(4)}"
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(fd, payload)
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(str(tmp), str(path))


def _safe_write(state: TelemetryState) -> None:
    try:
        _atomic_write(get_telemetry_config_path(), state)
    except Exception:
        _logger.debug("Failed to write telemetry state", exc_info=True)


def load_or_create() -> TelemetryState:
    """Return persisted state, generating a fresh install id on first use.

    Never raises; returns an in-memory default if the home dir is unwritable.
    """
    existing = _load_raw()
    if existing is not None:
        if not existing.install_id:
            existing.install_id = uuid.uuid4().hex
            _safe_write(existing)
        return existing
    state = TelemetryState(
        schema_version=SCHEMA_VERSION,
        install_id=uuid.uuid4().hex,
        enabled=True,
        notice_shown=False,
        created_at=_now_iso(),
    )
    try:
        return _atomic_create(get_telemetry_config_path(), state)
    except Exception:
        _logger.debug("Failed to create telemetry state", exc_info=True)
        return state


# ---------------------------------------------------------------------------
# Opt-out resolution
# ---------------------------------------------------------------------------


def _truthy(value: str | None) -> bool:
    return value is not None and value.strip().lower() not in {"", "0", "false"}


def _env_decision() -> tuple[bool | None, str]:
    """Return an env-based (decision, reason), or ``(None, "")`` if env has no opinion.

    ``DO_NOT_TRACK`` is the hard kill switch and is checked first, so it beats
    even an explicit ``INITRUNNER_TELEMETRY=on``.
    """
    if _truthy(os.environ.get(_DO_NOT_TRACK)):
        return False, "do-not-track"
    raw = os.environ.get(_INITRUNNER_TELEMETRY)
    if raw is not None:
        value = raw.strip().lower()
        if value in _OFF_VALUES:
            return False, "env-opt-out"
        if value in _ON_VALUES:
            return True, "env-opt-in"
    return None, ""


def _is_ci() -> bool:
    return _truthy(os.environ.get("CI"))


def resolve_enabled() -> tuple[bool, str]:
    """Resolve whether telemetry is enabled and why. Never raises, never sends.

    Precedence (first match wins): ``DO_NOT_TRACK`` > ``INITRUNNER_TELEMETRY`` >
    CI default-off > persisted opt-out > default on. Reads only env vars and the
    existing config file, so the disabled path never creates state or touches the
    network.
    """
    try:
        decision, reason = _env_decision()
        if decision is not None:
            return decision, reason
        if _is_ci():
            return False, "ci"
        state = _load_raw()
        if state is not None and not state.enabled:
            return False, "config-opt-out"
        return True, "enabled"
    except Exception:
        _logger.debug("resolve_enabled failed; disabling", exc_info=True)
        return False, "error"


# ---------------------------------------------------------------------------
# Mutators (used by `initrunner telemetry ...`)
# ---------------------------------------------------------------------------


def set_enabled(enabled: bool) -> TelemetryState:
    state = load_or_create()
    state.enabled = enabled
    _safe_write(state)
    return state


def mark_notice_shown() -> None:
    state = load_or_create()
    if state.notice_shown:
        return
    state.notice_shown = True
    _safe_write(state)


def reset_install_id() -> TelemetryState:
    state = load_or_create()
    state.install_id = uuid.uuid4().hex
    _safe_write(state)
    return state
