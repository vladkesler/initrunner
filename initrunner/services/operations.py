"""Audit queries, ingestion, triggers, and MCP introspection."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

    from initrunner.agent.schema.role import RoleDefinition
    from initrunner.audit.logger import AuditLogger, AuditRecord
    from initrunner.ingestion.pipeline import FileStatus, IngestStats
    from initrunner.triggers.base import TriggerEvent
    from initrunner.triggers.dispatcher import TriggerDispatcher


def query_audit_sync(
    *,
    agent_name: str | None = None,
    since: str | None = None,
    until: str | None = None,
    limit: int = 100,
    audit_logger: AuditLogger | None = None,
) -> list[AuditRecord]:
    """Query audit records (sync)."""
    if audit_logger is not None:
        return audit_logger.query(agent_name=agent_name, since=since, until=until, limit=limit)
    from initrunner.audit.logger import DEFAULT_DB_PATH
    from initrunner.audit.logger import AuditLogger as _AuditLogger

    db_path = DEFAULT_DB_PATH
    if not db_path.exists():
        return []
    with _AuditLogger(db_path) as logger:
        return logger.query(agent_name=agent_name, since=since, until=until, limit=limit)


def run_ingest_sync(
    role: RoleDefinition,
    role_path: Path,
    *,
    force: bool = False,
    progress_callback: Callable[[Path, FileStatus], None] | None = None,
) -> IngestStats | None:
    """Run ingestion pipeline (sync)."""
    from initrunner.agent.loader import _load_dotenv
    from initrunner.ingestion.pipeline import run_ingest

    _load_dotenv(role_path.parent)

    if role.spec.ingest is None:
        return None
    return run_ingest(
        role.spec.ingest,
        role.metadata.name,
        provider=role.spec.model.provider,
        base_dir=role_path.parent,
        force=force,
        progress_callback=progress_callback,
    )


def start_triggers_sync(
    role: RoleDefinition,
    callback: Callable[[TriggerEvent], None],
) -> TriggerDispatcher:
    """Build and start a TriggerDispatcher (sync). Returns the dispatcher."""
    from initrunner.triggers.dispatcher import TriggerDispatcher

    dispatcher = TriggerDispatcher(role.spec.triggers, callback)
    dispatcher.start_all()
    return dispatcher


# ---------------------------------------------------------------------------
# MCP introspection
# ---------------------------------------------------------------------------


def list_mcp_tools_sync(
    role_path: Path,
    index: int | None = None,
) -> list[tuple[str, str, str]]:
    """List tools from MCP servers configured in a role file (sync).

    Returns ``(server_summary, tool_name, tool_description)`` tuples.
    Does not require valid LLM API keys.
    """
    from initrunner.mcp.introspect import list_mcp_tools

    return list_mcp_tools(role_path, index=index)
