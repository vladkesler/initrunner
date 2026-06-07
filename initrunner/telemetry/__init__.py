"""Anonymous, opt-in product-usage telemetry for the InitRunner CLI.

What it answers: is InitRunner being used, which commands, on what platform and
version, and where it errors. It is distinct from the user-facing OpenTelemetry
agent observability and from the local HMAC audit trail (neither of which is
ever transmitted).

Telemetry is opt-in: nothing is sent until the user accepts the one-time
first-run prompt (or runs ``initrunner telemetry enable``). The public API is
best-effort: it never raises, never blocks process exit, and sends nothing when
telemetry is undecided or disabled (``DO_NOT_TRACK``, ``INITRUNNER_TELEMETRY=off``,
CI, or ``initrunner telemetry disable``). Only an allowlist of safe primitives is
sent; see ``_events.py`` and ``docs/operations/telemetry.md``.
"""

from __future__ import annotations

import logging

from initrunner.config import get_telemetry_config_path

from . import _config, _events, _sender

_logger = logging.getLogger(__name__)

__all__ = [
    "consent_needed",
    "disable",
    "enable",
    "flush",
    "record_command",
    "reset",
    "resolve_enabled",
    "send_first_run",
    "set_consent",
    "status",
]


def resolve_enabled() -> tuple[bool, str]:
    """Return ``(enabled, reason)``. Never raises, never sends."""
    return _config.resolve_enabled()


def consent_needed() -> bool:
    """True when consent is undecided with no env/CI override (prompt the user)."""
    try:
        return _config.resolve_enabled()[1] == "unset"
    except Exception:
        _logger.debug("consent_needed failed", exc_info=True)
        return False


def status() -> dict[str, object]:
    """Return a read-only status summary for ``doctor`` / ``telemetry status``."""
    enabled, reason = _config.resolve_enabled()
    state = _config._load_raw()
    return {
        "enabled": enabled,
        "reason": reason,
        "consent": state.consent if state else None,
        "install_id": state.install_id if state else None,
        "path": str(get_telemetry_config_path()),
    }


def set_consent(granted: bool) -> None:
    """Persist an explicit consent decision. Never raises."""
    try:
        _config.set_consent(granted)
    except Exception:
        _logger.debug("telemetry set_consent failed", exc_info=True)


def send_first_run() -> None:
    """Emit the single ``cli_first_run`` event once consent is granted. Never raises.

    Lets distinct installs be counted without any identifying data. Safe to call
    more than once; it only sends when telemetry currently resolves to enabled.
    """
    try:
        enabled, _ = _config.resolve_enabled()
        if not enabled:
            return
        state = _config.load_or_create()
        if state.install_id:
            _sender.enqueue("cli_first_run", state.install_id, _events.first_run_properties())
    except Exception:
        _logger.debug("telemetry send_first_run failed", exc_info=True)


def record_command(
    *,
    command: str | None,
    status: str,
    exit_code: int | None = None,
    error_kind: str | None = None,
    duration_ms: float | None = None,
    is_tty: bool = False,
) -> None:
    """Buffer one ``cli_command`` event. Never raises; no-op when disabled."""
    try:
        enabled, _ = _config.resolve_enabled()
        if not enabled:
            return
        state = _config.load_or_create()
        if not state.install_id:
            return
        properties = _events.command_properties(
            command=command,
            status=status,
            exit_code=exit_code,
            error_kind=error_kind,
            duration_ms=duration_ms,
            is_tty=is_tty,
        )
        _sender.enqueue("cli_command", state.install_id, properties)
    except Exception:
        _logger.debug("telemetry record_command failed", exc_info=True)


def flush() -> None:
    """Send buffered events with a bounded timeout. Never raises, never blocks exit."""
    _sender.flush()


def enable() -> None:
    """Persist consent (explicit opt-in; clears a prior ``disable``)."""
    _config.set_consent(True)


def disable() -> None:
    """Persist a refusal (explicit opt-out)."""
    _config.set_consent(False)


def reset() -> str:
    """Rotate the anonymous install id and return the new value."""
    return _config.reset_install_id().install_id
