"""Out-of-process kernel isolation for subprocess tools.

Separate from ``initrunner.agent.sandbox`` (PEP 578 audit-hook sandbox).
That module is per-thread Python audit hooks; this package is OS-level
isolation (bubblewrap, Docker) for tool subprocesses.
"""

from __future__ import annotations

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

_default_audit: AuditLogger | NullAuditLogger | None = None


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
]
