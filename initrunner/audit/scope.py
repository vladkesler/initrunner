"""Per-run audit context for code that runs deep inside an agent run.

Tool wrappers and capabilities have no audit logger in hand. The executor and
the API server open an :func:`audit_scope` around each run, and this module's
:func:`log_security_event` writes to it. Outside a scope it does nothing.
"""

from __future__ import annotations

import contextvars
from collections.abc import Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from initrunner.audit.logger import AuditLogger

_current: contextvars.ContextVar[tuple[AuditLogger, str] | None] = contextvars.ContextVar(
    "initrunner_audit_scope", default=None
)


def set_audit_scope(
    audit_logger: AuditLogger | None, agent_name: str
) -> contextvars.Token[tuple[AuditLogger, str] | None]:
    """Route :func:`log_security_event` calls in this context to *audit_logger*."""
    return _current.set((audit_logger, agent_name) if audit_logger is not None else None)


def reset_audit_scope(token: contextvars.Token[tuple[AuditLogger, str] | None]) -> None:
    _current.reset(token)


@contextmanager
def audit_scope(audit_logger: AuditLogger | None, agent_name: str) -> Iterator[None]:
    """:func:`set_audit_scope` for the duration of a ``with`` block."""
    token = set_audit_scope(audit_logger, agent_name)
    try:
        yield
    finally:
        reset_audit_scope(token)


def log_security_event(event_type: str, details: str) -> None:
    """Write a security event for the current run. Never raises."""
    scope = _current.get()
    if scope is None:
        return
    audit_logger, agent_name = scope
    audit_logger.log_security_event(event_type=event_type, agent_name=agent_name, details=details)
