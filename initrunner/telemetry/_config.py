"""Telemetry consent state: an anonymous install id plus a consent decision.

State lives at ``~/.initrunner/telemetry.json`` (mode 0600). The install id is
created silently on first use, like ``audit_hmac.key`` (see ``audit/_hmac.py``),
but telemetry is opt-in: nothing is sent until ``consent`` is ``"granted"``.
Every function here is best-effort: failures are logged at debug and never
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
from typing import Literal

from pydantic import BaseModel, PrivateAttr

from initrunner.config import get_telemetry_config_path

_logger = logging.getLogger(__name__)

SCHEMA_VERSION = 2

# Tri-state consent: never asked, accepted, or refused.
Consent = Literal["unset", "granted", "denied"]

_DO_NOT_TRACK = "DO_NOT_TRACK"
_INITRUNNER_TELEMETRY = "INITRUNNER_TELEMETRY"

_OFF_VALUES = frozenset({"0", "false", "off", "no", "disable", "disabled"})
_ON_VALUES = frozenset({"1", "true", "on", "yes", "enable", "enabled"})


class TelemetryState(BaseModel):
    """Persisted telemetry consent record."""

    schema_version: int = SCHEMA_VERSION
    install_id: str = ""
    consent: Consent = "unset"
    created_at: str = ""

    # Set in-memory by ``_load_raw`` when a legacy (v1) record was migrated, so
    # ``load_or_create`` knows to write the upgrade back once. Excluded from
    # ``model_dump_json`` (PrivateAttr), so it never lands in the file.
    _needs_persist: bool = PrivateAttr(default=False)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


# ---------------------------------------------------------------------------
# Read / write
# ---------------------------------------------------------------------------


def _migrate(data: dict) -> bool:
    """Upgrade a parsed record to the current schema in place. Return True if changed.

    v1 stored ``enabled``/``notice_shown``; v2 stores tri-state ``consent``. An
    explicit ``enabled: false`` (someone ran ``telemetry disable``) maps to
    ``denied`` so it is never re-asked; anything else maps to ``unset`` so the
    user is prompted under the new opt-in default.
    """
    if "consent" in data:
        return False
    data["consent"] = "denied" if data.get("enabled") is False else "unset"
    data["schema_version"] = SCHEMA_VERSION
    return True


def _load_raw() -> TelemetryState | None:
    """Return the persisted state, or ``None`` if absent/unreadable. Never raises.

    Migrates legacy records in memory only; persistence is deferred to
    ``load_or_create`` so ``resolve_enabled`` stays read-only.
    """
    try:
        path = get_telemetry_config_path()
        if not path.is_file():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return None
        migrated = _migrate(data)
        state = TelemetryState.model_validate(data)
        state._needs_persist = migrated
        return state
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
            existing._needs_persist = True
        if existing._needs_persist:
            _safe_write(existing)
            existing._needs_persist = False
        return existing
    state = TelemetryState(
        schema_version=SCHEMA_VERSION,
        install_id=uuid.uuid4().hex,
        consent="unset",
        created_at=_now_iso(),
    )
    try:
        return _atomic_create(get_telemetry_config_path(), state)
    except Exception:
        _logger.debug("Failed to create telemetry state", exc_info=True)
        return state


# ---------------------------------------------------------------------------
# Consent resolution
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
    CI default-off > persisted consent. Telemetry is opt-in, so an undecided or
    absent record resolves to off. Reads only env vars and the existing config
    file, so the disabled path never creates state or touches the network.
    """
    try:
        decision, reason = _env_decision()
        if decision is not None:
            return decision, reason
        if _is_ci():
            return False, "ci"
        state = _load_raw()
        consent = state.consent if state is not None else "unset"
        if consent == "granted":
            return True, "consent-granted"
        if consent == "denied":
            return False, "consent-denied"
        return False, "unset"
    except Exception:
        _logger.debug("resolve_enabled failed; disabling", exc_info=True)
        return False, "error"


# ---------------------------------------------------------------------------
# Mutators (used by `initrunner telemetry ...`)
# ---------------------------------------------------------------------------


def set_consent(granted: bool) -> TelemetryState:
    """Persist an explicit consent decision (``granted`` or ``denied``)."""
    state = load_or_create()
    state.consent = "granted" if granted else "denied"
    _safe_write(state)
    return state


def reset_install_id() -> TelemetryState:
    state = load_or_create()
    state.install_id = uuid.uuid4().hex
    _safe_write(state)
    return state
