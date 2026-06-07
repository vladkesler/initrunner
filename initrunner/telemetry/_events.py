"""Event property construction. Allowlist only, never free text.

Properties are assembled from a fixed set of safe primitives, never by
reflecting over argv / prompts / role files. ``_finalize`` is the single gate:
it drops any key not in ``_ALLOWED_PROPERTY_KEYS``, scrubs string values through
the audit secret regex, and stamps the PostHog control properties that keep
events anonymous.
"""

from __future__ import annotations

import os
import platform
import sys

from initrunner import __version__
from initrunner.audit._redact import scrub_secrets

_LIB = "initrunner-cli"

# Known top-level CLI commands and sub-app names. Anything else maps to "other"
# so a typo, alias, or custom command can never leak through.
_KNOWN_COMMANDS = frozenset(
    {
        "run", "new", "setup", "doctor", "examples", "export",
        "test", "ingest", "validate", "configure",
        "dashboard", "desktop", "a2a", "flow", "mcp",
        "install", "uninstall", "list", "update", "search", "info",
        "publish", "pull", "login", "logout", "whoami",
        "plugins", "skill", "memory", "audit", "cost", "vault",
        "approve", "pending", "hub", "telemetry",
        "help", "version",
    }
)  # fmt: skip

# Exception classes kept verbatim; everything else collapses to "OtherError".
# Messages and tracebacks are never sent.
_KNOWN_ERRORS = frozenset(
    {
        "KeyboardInterrupt", "SystemExit", "FileNotFoundError", "PermissionError",
        "IsADirectoryError", "NotADirectoryError", "TimeoutError", "ConnectionError",
        "ValueError", "TypeError", "KeyError", "RuntimeError", "OSError",
        "ImportError", "ModuleNotFoundError", "MissingExtraError",
        "ValidationError", "UsageError",
    }
)  # fmt: skip

# The ONLY property keys allowed to leave the process.
_ALLOWED_PROPERTY_KEYS = frozenset(
    {
        # event-specific
        "command", "status", "exit_code", "error_kind", "duration_bucket",
        "is_tty", "is_ci", "install_method",
        # super properties
        "os", "python_version", "initrunner_version", "$lib",
        # PostHog control properties (anonymous event, no geo lookup)
        "$process_person_profile", "$geoip_disable",
    }
)  # fmt: skip


def normalize_command(command: str | None) -> str:
    if not command:
        return "other"
    return command if command in _KNOWN_COMMANDS else "other"


def normalize_error_kind(error_kind: str | None) -> str | None:
    if not error_kind:
        return None
    return error_kind if error_kind in _KNOWN_ERRORS else "OtherError"


def duration_bucket(duration_ms: float | None) -> str:
    if duration_ms is None:
        return "unknown"
    seconds = duration_ms / 1000.0
    if seconds < 1:
        return "<1s"
    if seconds < 5:
        return "1-5s"
    if seconds < 30:
        return "5-30s"
    return "30s+"


def _is_ci() -> bool:
    value = os.environ.get("CI")
    return value is not None and value.strip().lower() not in {"", "0", "false"}


def install_method() -> str:
    """Best-effort install method. Never raises."""
    try:
        if os.path.exists("/.dockerenv") or os.environ.get("INITRUNNER_IN_DOCKER"):
            return "docker"
        exe = (sys.argv[0] or "").lower()
        if "pipx" in exe or os.environ.get("PIPX_HOME"):
            return "pipx"
        if "uv" in os.environ.get("UV", "") or "/uv/" in exe:
            return "uv"
        return "pip"
    except Exception:
        return "unknown"


def _super_properties() -> dict[str, object]:
    return {
        "os": platform.system() or "unknown",
        "python_version": f"{sys.version_info.major}.{sys.version_info.minor}",
        "initrunner_version": __version__,
        "$lib": _LIB,
    }


def _finalize(props: dict[str, object]) -> dict[str, object]:
    """Force anonymity, drop unknown keys, scrub string values."""
    props["$process_person_profile"] = False
    props["$geoip_disable"] = True
    out: dict[str, object] = {}
    for key, value in props.items():
        if key not in _ALLOWED_PROPERTY_KEYS:
            continue
        if isinstance(value, str):
            value = scrub_secrets(value)
        out[key] = value
    return out


def command_properties(
    *,
    command: str | None,
    status: str,
    exit_code: int | None,
    error_kind: str | None,
    duration_ms: float | None,
    is_tty: bool,
) -> dict[str, object]:
    props = _super_properties()
    props.update(
        {
            "command": normalize_command(command),
            "status": status,
            "exit_code": exit_code,
            "duration_bucket": duration_bucket(duration_ms),
            "is_tty": bool(is_tty),
            "is_ci": _is_ci(),
        }
    )
    normalized_error = normalize_error_kind(error_kind)
    if normalized_error is not None:
        props["error_kind"] = normalized_error
    if exit_code is None:
        props.pop("exit_code", None)
    return _finalize(props)


def first_run_properties() -> dict[str, object]:
    props = _super_properties()
    props["install_method"] = install_method()
    return _finalize(props)
