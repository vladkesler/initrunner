"""Anonymous, opt-out product-usage telemetry for the InitRunner CLI.

What it answers: is InitRunner being used, which commands, on what platform and
version, and where it errors. It is distinct from the user-facing OpenTelemetry
agent observability and from the local HMAC audit trail (neither of which is
ever transmitted).

The public API is best-effort: it never raises, never blocks process exit, and
sends nothing when telemetry is disabled (``DO_NOT_TRACK``,
``INITRUNNER_TELEMETRY=off``, CI, or ``initrunner telemetry disable``). Only an
allowlist of safe primitives is sent; see ``_events.py`` and
``docs/operations/telemetry.md``.
"""

from __future__ import annotations

import logging

from initrunner.config import get_telemetry_config_path

from . import _config, _events, _sender

_logger = logging.getLogger(__name__)

__all__ = [
    "disable",
    "enable",
    "flush",
    "notice_if_first_run",
    "record_command",
    "reset",
    "resolve_enabled",
    "status",
]

_NOTICE = (
    "InitRunner collects anonymous usage data (which command ran, version, OS, and error "
    "type) to guide what to work on next. No prompts, files, paths, arguments, or API keys "
    "are sent, and it is tied to a random id, not to you. Turn it off with: "
    "initrunner telemetry disable  (or set DO_NOT_TRACK=1). "
    "Details: docs/operations/telemetry.md"
)


def resolve_enabled() -> tuple[bool, str]:
    """Return ``(enabled, reason)``. Never raises, never sends."""
    return _config.resolve_enabled()


def status() -> dict[str, object]:
    """Return a read-only status summary for ``doctor`` / ``telemetry status``."""
    enabled, reason = _config.resolve_enabled()
    state = _config._load_raw()
    return {
        "enabled": enabled,
        "reason": reason,
        "install_id": state.install_id if state else None,
        "path": str(get_telemetry_config_path()),
    }


def notice_if_first_run() -> None:
    """Show the one-time notice before the first send (TTY or not). Never raises.

    Also emits the single ``cli_first_run`` event the first time telemetry is
    active, so distinct installs can be counted without any identifying data.
    """
    try:
        enabled, _ = _config.resolve_enabled()
        if not enabled:
            return
        state = _config.load_or_create()
        if state.notice_shown:
            return
        import sys

        sys.stderr.write(_NOTICE + "\n")
        _config.mark_notice_shown()
        if state.install_id:
            _sender.enqueue("cli_first_run", state.install_id, _events.first_run_properties())
    except Exception:
        _logger.debug("telemetry notice failed", exc_info=True)


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
    """Persist an opt-in (clears a prior ``disable``)."""
    _config.set_enabled(True)


def disable() -> None:
    """Persist an opt-out."""
    _config.set_enabled(False)


def reset() -> str:
    """Rotate the anonymous install id and return the new value."""
    return _config.reset_install_id().install_id
