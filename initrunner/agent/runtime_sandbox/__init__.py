"""Out-of-process kernel isolation for subprocess tools.

Separate from ``initrunner.agent.sandbox`` (PEP 578 audit-hook sandbox).
That module is per-thread Python audit hooks; this package is OS-level
isolation (bubblewrap, Docker) for tool subprocesses.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from initrunner.agent.runtime_sandbox.base import (
    SandboxBackend,
    SandboxConfigError,
    SandboxResult,
    SandboxUnavailableError,
)
from initrunner.agent.runtime_sandbox.null import NullBackend
from initrunner.agent.runtime_sandbox.select import resolve_backend

if TYPE_CHECKING:
    from initrunner.audit.logger import AuditLogger
    from initrunner.audit.null import NullAuditLogger

_logger = logging.getLogger(__name__)

_default_audit: AuditLogger | NullAuditLogger | None = None


def warn_if_unsandboxed(backend: object, tool_name: str) -> None:
    """Warn once at build time when an exec tool will run on the host.

    With ``security.sandbox.backend: none`` (the default), shell/python/script
    tools execute model-generated commands with this process's own privileges.
    That is a deliberate opt-out, but it should be visible -- real isolation
    needs ``backend: bwrap`` or ``docker``.
    """
    if getattr(backend, "name", None) == "none":
        _logger.warning(
            "Tool %r runs on the host with no sandbox (security.sandbox.backend: none); "
            "model-driven commands execute with this process's privileges. Set "
            "security.sandbox.backend to 'bwrap' or 'docker' to contain them.",
            tool_name,
        )


def set_default_audit_logger(audit: AuditLogger | NullAuditLogger | None) -> None:
    """Set the audit logger used when resolve_backend() is called without one.

    Wired by the CLI so `sandbox.exec` events flow to the user's audit DB
    without every call site having to thread the logger through explicitly.
    """
    global _default_audit
    _default_audit = audit


def get_default_audit_logger() -> AuditLogger | NullAuditLogger | None:
    return _default_audit


__all__ = [
    "NullBackend",
    "SandboxBackend",
    "SandboxConfigError",
    "SandboxResult",
    "SandboxUnavailableError",
    "get_default_audit_logger",
    "resolve_backend",
    "set_default_audit_logger",
    "warn_if_unsandboxed",
]
