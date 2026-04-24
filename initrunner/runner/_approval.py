"""Shared paused-run handling for runner modes.

``render_paused_run()`` shows the user which tool calls are awaiting
approval and where to resume them. ``persist_paused_run_if_needed()``
wraps the services facade with a no-op when there's no audit logger
(e.g. ``--no-audit``), emitting a stderr warning in that case — a paused
run without persistence cannot be resumed later.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from initrunner.runner.display import console

if TYPE_CHECKING:
    from initrunner.agent.executor import RunResult
    from initrunner.agent.schema.role import RoleDefinition
    from initrunner.audit.logger import AuditLogger

logger = logging.getLogger(__name__)


def render_paused_run(result: RunResult, *, run_cmd: str = "initrunner approve") -> None:
    """Print a concise summary of pending approvals and the resume hint."""
    count = len(result.pending_approvals)
    console.print(
        f"\n[yellow]Run {result.run_id} paused — {count} tool "
        f"call{'s' if count != 1 else ''} awaiting approval.[/yellow]"
    )
    for p in result.pending_approvals:
        console.print(
            f"  [magenta]{p.tool_call_id}[/magenta]  [bold]{p.tool_name}[/bold]  {p.arguments}"
        )
    console.print(f"\nResume with: [bold]{run_cmd} {result.run_id} --all[/bold]")


def persist_paused_run_if_needed(
    result: RunResult,
    role: RoleDefinition,
    message_history: list,
    *,
    audit_logger: AuditLogger | None,
    role_path: Path | None,
) -> bool:
    """Persist pending approvals if an audit logger is available.

    Returns True when state was persisted, False otherwise. Callers must
    treat False as "this paused run is not resumable" and surface a
    warning — PydanticAI's deferred contract needs the exact message
    history we just saw.
    """
    if audit_logger is None:
        logger.warning(
            "Run %s paused but no audit logger is active — state cannot be resumed.",
            result.run_id,
        )
        console.print(
            "[red]Warning:[/red] audit logging is disabled, so this paused run "
            "cannot be resumed later."
        )
        return False

    from initrunner.services.execution import persist_paused_run

    persist_paused_run(audit_logger, result, role, message_history, role_path=role_path)
    return True
