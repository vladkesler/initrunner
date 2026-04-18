"""No-op audit logger for sandbox backends that don't need persistence."""

from __future__ import annotations


class NullAuditLogger:
    """Drop-in for AuditLogger.log_security_event -- does nothing."""

    def log_security_event(
        self,
        event_type: str,
        agent_name: str,
        details: str,
        source_ip: str | None = None,
        principal_id: str | None = None,
    ) -> None:
        pass
