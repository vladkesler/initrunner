"""Audit queries, ingestion, triggers, MCP introspection, and MCP gateway."""

from __future__ import annotations

from dataclasses import dataclass
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
    run_id: str | None = None,
    trigger_type: str | None = None,
    principal_id: str | None = None,
    since: str | None = None,
    until: str | None = None,
    limit: int = 100,
    audit_logger: AuditLogger | None = None,
    audit_db: Path | None = None,
    exclude_trigger_types: list[str] | None = None,
) -> list[AuditRecord]:
    """Query audit records (sync)."""
    kwargs = dict(
        agent_name=agent_name,
        run_id=run_id,
        trigger_type=trigger_type,
        principal_id=principal_id,
        since=since,
        until=until,
        limit=limit,
        exclude_trigger_types=exclude_trigger_types,
    )
    if audit_logger is not None:
        return audit_logger.query(**kwargs)
    from initrunner.audit.logger import DEFAULT_DB_PATH
    from initrunner.audit.logger import AuditLogger as _AuditLogger

    db_path = audit_db or DEFAULT_DB_PATH
    if not db_path.exists():
        return []
    with _AuditLogger(db_path) as logger:
        return logger.query(**kwargs)


def audit_prune_sync(
    *,
    retention_days: int = 90,
    max_records: int = 100_000,
    audit_db: Path | None = None,
) -> int:
    """Prune old audit records (sync). Returns number of records deleted."""
    from initrunner.audit.logger import DEFAULT_DB_PATH
    from initrunner.audit.logger import AuditLogger as _AuditLogger

    db_path = audit_db or DEFAULT_DB_PATH
    if not db_path.exists():
        return 0
    with _AuditLogger(db_path) as logger:
        return logger.prune(retention_days=retention_days, max_records=max_records)


@dataclass
class TopAgent:
    """Agent ranked by run count."""

    name: str
    count: int
    avg_duration_ms: int


@dataclass
class AuditStats:
    """Aggregate audit statistics."""

    total_runs: int
    success_rate: float
    total_tokens: int
    avg_duration_ms: int
    top_agents: list[TopAgent]


@dataclass
class TriggerStat:
    """Per-trigger-type operational stats derived from the audit trail."""

    trigger_type: str
    fire_count: int
    success_count: int
    fail_count: int
    last_fire_time: str | None
    avg_duration_ms: int
    last_error: str | None


def audit_stats_sync(
    *,
    agent_name: str | None = None,
    since: str | None = None,
    until: str | None = None,
    audit_db: Path | None = None,
) -> AuditStats:
    """Compute aggregate audit stats (sync)."""
    from initrunner.audit.logger import DEFAULT_DB_PATH
    from initrunner.audit.logger import AuditLogger as _AuditLogger

    db_path = audit_db or DEFAULT_DB_PATH
    if not db_path.exists():
        return AuditStats(
            total_runs=0,
            success_rate=0.0,
            total_tokens=0,
            avg_duration_ms=0,
            top_agents=[],
        )
    with _AuditLogger(db_path) as logger:
        return logger.stats(agent_name=agent_name, since=since, until=until)


def trigger_stats_sync(
    *,
    agent_name: str,
    audit_db: Path | None = None,
) -> list[TriggerStat]:
    """Per-trigger-type stats for an agent, derived from the audit trail (sync)."""
    from initrunner.audit.logger import DEFAULT_DB_PATH
    from initrunner.audit.logger import AuditLogger as _AuditLogger

    db_path = audit_db or DEFAULT_DB_PATH
    if not db_path.exists():
        return []
    with _AuditLogger(db_path) as logger:
        return logger.trigger_stats(agent_name=agent_name)


def next_cron_check(schedule: str) -> str | None:
    """Compute the next cron fire time in UTC. Returns ISO string or None on error."""
    try:
        from datetime import UTC, datetime

        from croniter import croniter  # type: ignore[import-not-found]

        now = datetime.now(UTC)
        cron = croniter(schedule, now)
        return cron.get_next(datetime).isoformat()
    except Exception:
        return None


def next_heartbeat_check(last_fire_time: str | None, interval_seconds: int) -> str | None:
    """Compute the next heartbeat check from last fire + interval. Returns None when unknown."""
    if not last_fire_time:
        return None
    try:
        from datetime import UTC, datetime, timedelta

        last = datetime.fromisoformat(last_fire_time)
        if last.tzinfo is None:
            last = last.replace(tzinfo=UTC)
        return (last + timedelta(seconds=interval_seconds)).isoformat()
    except Exception:
        return None


def query_delegate_events_sync(
    *,
    source_service: str | None = None,
    target_service: str | None = None,
    status: str | None = None,
    source_run_id: str | None = None,
    compose_name: str | None = None,
    since: str | None = None,
    until: str | None = None,
    limit: int = 1000,
    audit_db: Path | None = None,
) -> list:
    """Query delegate routing events from the audit trail (sync)."""
    from initrunner.audit.logger import DEFAULT_DB_PATH
    from initrunner.audit.logger import AuditLogger as _AuditLogger

    db_path = audit_db or DEFAULT_DB_PATH
    if not db_path.exists():
        return []
    with _AuditLogger(db_path) as logger:
        return logger.query_delegate_events(
            source_service=source_service,
            target_service=target_service,
            status=status,
            source_run_id=source_run_id,
            compose_name=compose_name,
            since=since,
            until=until,
            limit=limit,
        )


def resolve_sources_sync(
    sources: list[str],
    *,
    base_dir: Path | None = None,
) -> tuple[list[Path], list[str]]:
    """Resolve ingest source patterns to files and URLs (sync)."""
    from initrunner.ingestion.pipeline import resolve_sources

    return resolve_sources(sources, base_dir=base_dir)


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
        provider=role.spec.model.provider,  # type: ignore[union-attr]
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


# ---------------------------------------------------------------------------
# MCP gateway
# ---------------------------------------------------------------------------


def build_mcp_gateway_sync(
    role_paths: list[Path],
    *,
    server_name: str = "initrunner",
    audit_logger: AuditLogger | None = None,
    pass_through: bool = False,
    extra_skill_dirs: list[Path] | None = None,
) -> object:
    """Build an MCP gateway server (sync). Returns a FastMCP instance."""
    from initrunner.mcp.gateway import build_mcp_gateway

    return build_mcp_gateway(
        role_paths,
        server_name=server_name,
        audit_logger=audit_logger,
        pass_through=pass_through,
        extra_skill_dirs=extra_skill_dirs,
    )


# ---------------------------------------------------------------------------
# MCP toolkit
# ---------------------------------------------------------------------------


def build_toolkit_sync(
    *,
    config_path: Path | None = None,
    tool_names: list[str] | None = None,
    server_name: str | None = None,
) -> object:
    """Build an MCP toolkit server (sync). Returns a FastMCP instance."""
    from initrunner.mcp.toolkit import ToolkitConfig, build_toolkit, load_toolkit_config

    config: ToolkitConfig | None = None
    if config_path is not None:
        config = load_toolkit_config(config_path)
    if config is None:
        config = ToolkitConfig()
    if server_name is not None:
        config.server_name = server_name
    return build_toolkit(config, tool_names=tool_names)
