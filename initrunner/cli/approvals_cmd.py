"""Approvals CLI: ``initrunner approve`` and ``initrunner pending``.

Resume paused runs by resolving the tool-call approvals that
``approval: required`` tools raise.
"""

from __future__ import annotations

import json as _json
from pathlib import Path
from typing import Annotated

import typer

from initrunner.cli._helpers import console
from initrunner.cli._options import AuditDbOption


def _load_logger(audit_db: Path | None):
    from initrunner.audit.logger import DEFAULT_DB_PATH, AuditLogger

    db_path = Path(audit_db or DEFAULT_DB_PATH)
    if not db_path.exists():
        console.print(f"[red]Error:[/red] Audit database not found at {db_path}")
        raise typer.Exit(1)
    return AuditLogger(db_path=db_path)


def pending(
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Emit machine-readable JSON instead of a table."),
    ] = False,
    limit: Annotated[int, typer.Option(help="Maximum rows to return.")] = 100,
    audit_db: AuditDbOption = None,
) -> None:
    """List unresolved tool-call approval requests."""
    logger = _load_logger(audit_db)
    try:
        rows = logger.list_pending_approvals(limit=limit)
    finally:
        logger.close()

    if json_output:
        payload = [
            {
                "run_id": r.run_id,
                "tool_call_id": r.tool_call_id,
                "tool_name": r.tool_name,
                "agent_name": r.agent_name,
                "role_path": r.role_path,
                "arguments": _safe_load(r.arguments_json),
                "created_at": r.created_at,
            }
            for r in rows
        ]
        console.print_json(data=payload)
        return

    if not rows:
        console.print("[dim]No pending approvals.[/dim]")
        return

    from rich.table import Table

    table = Table(title=f"Pending approvals ({len(rows)})")
    table.add_column("run_id", style="cyan", no_wrap=True)
    table.add_column("tool_call_id", style="magenta", no_wrap=True)
    table.add_column("tool", style="bold")
    table.add_column("agent")
    table.add_column("created_at", style="dim")
    table.add_column("arguments", overflow="fold")
    for r in rows:
        table.add_row(
            r.run_id,
            r.tool_call_id,
            r.tool_name,
            r.agent_name,
            r.created_at,
            _preview(r.arguments_json, 80),
        )
    console.print(table)


def approve(
    run_id: Annotated[str, typer.Argument(help="Paused run id.")],
    tool_call_id: Annotated[
        str | None,
        typer.Option("--tool-call-id", help="Resolve this tool-call only. Omit with --all."),
    ] = None,
    deny: Annotated[bool, typer.Option("--deny", help="Deny instead of approve.")] = False,
    all_: Annotated[
        bool,
        typer.Option("--all", help="Resolve every unresolved approval for this run."),
    ] = False,
    resolved_by: Annotated[
        str | None,
        typer.Option(help="Operator identifier recorded in the audit trail."),
    ] = None,
    audit_db: AuditDbOption = None,
) -> None:
    """Resolve one or more paused tool-call approvals and resume the run.

    Either supply ``--tool-call-id ID`` for a single call or ``--all`` to
    apply the same decision to every unresolved call for the run. The
    process rebuilds the agent from the role YAML path that was persisted
    alongside the pending rows.
    """
    if bool(tool_call_id) == bool(all_):
        console.print(
            "[red]Error:[/red] pass exactly one of [bold]--tool-call-id[/bold] "
            "or [bold]--all[/bold]."
        )
        raise typer.Exit(2)

    logger = _load_logger(audit_db)
    try:
        rows = logger.load_pending_approvals(run_id)
        unresolved = [r for r in rows if r.resolved_at is None]
        if not unresolved:
            console.print(f"[yellow]No unresolved approvals for run {run_id!r}.[/yellow]")
            raise typer.Exit(1)

        role_paths = {r.role_path for r in unresolved if r.role_path}
        if len(role_paths) != 1 or next(iter(role_paths), None) is None:
            console.print(
                f"[red]Error:[/red] cannot resume run {run_id!r}: pending rows "
                "are missing or disagree on the role file."
            )
            raise typer.Exit(1)
        role_path = Path(next(iter(role_paths)))
        if not role_path.exists():
            console.print(f"[red]Error:[/red] Role file no longer exists at {role_path}.")
            raise typer.Exit(1)

        decision = not deny
        if all_:
            approvals = {r.tool_call_id: decision for r in unresolved}
        else:
            matches = [r for r in unresolved if r.tool_call_id == tool_call_id]
            if not matches:
                console.print(
                    f"[red]Error:[/red] tool_call_id {tool_call_id!r} is not "
                    f"pending for run {run_id!r}."
                )
                raise typer.Exit(1)
            # PydanticAI requires every pending approval to carry a decision
            # on resume. Default the others to denied so a single
            # --tool-call-id invocation still unblocks the run.
            approvals = {r.tool_call_id: False for r in unresolved}
            approvals[tool_call_id] = decision

        from initrunner.services.execution import build_agent_sync, resume_run_sync

        role, agent = build_agent_sync(role_path)
        result, _messages = resume_run_sync(
            agent,
            role,
            run_id,
            approvals,
            audit_logger=logger,
            resolved_by=resolved_by,
            role_path=role_path,
        )
    finally:
        logger.close()

    if result.status == "paused":
        console.print(
            f"[yellow]Run {run_id!r} paused again with "
            f"{len(result.pending_approvals)} new approval(s).[/yellow]"
        )
        for p in result.pending_approvals:
            console.print(f"  [magenta]{p.tool_call_id}[/magenta]  {p.tool_name}  {p.arguments}")
        console.print(f"Resume with: [bold]initrunner approve {run_id} --all[/bold]")
        raise typer.Exit(2)

    if not result.success:
        console.print(f"[red]Resume failed:[/red] {result.error}")
        raise typer.Exit(1)

    console.print("[green]Resumed.[/green]")
    if result.output:
        console.print(result.output)


def _preview(text: str, limit: int) -> str:
    text = text.replace("\n", " ").strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _safe_load(text: str):
    try:
        return _json.loads(text)
    except _json.JSONDecodeError:
        return text
