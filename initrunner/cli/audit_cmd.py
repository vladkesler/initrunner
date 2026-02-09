"""Audit commands: prune, export."""

from __future__ import annotations

import csv
import io
import json
import sys
from pathlib import Path
from typing import Annotated

import typer

from initrunner.cli._helpers import console

app = typer.Typer(help="Inspect and export audit records.")


@app.command("prune")
def audit_prune(
    retention_days: Annotated[
        int, typer.Option(help="Delete records older than this many days")
    ] = 90,
    max_records: Annotated[int, typer.Option(help="Maximum records to keep")] = 100_000,
    audit_db: Annotated[Path | None, typer.Option(help="Path to audit database")] = None,
) -> None:
    """Prune old audit records."""
    from initrunner.audit.logger import DEFAULT_DB_PATH
    from initrunner.audit.logger import AuditLogger as _AuditLogger

    db_path = audit_db or DEFAULT_DB_PATH
    if not db_path.exists():
        console.print(f"[red]Error:[/red] Audit database not found at {db_path}")
        raise typer.Exit(1)

    with _AuditLogger(db_path) as logger:
        deleted = logger.prune(retention_days=retention_days, max_records=max_records)

    console.print(f"[green]Pruned[/green] {deleted} record(s).")


@app.command("export")
def audit_export(
    format: Annotated[
        str, typer.Option("-f", "--format", help="Output format: json or csv")
    ] = "json",
    output: Annotated[
        Path | None, typer.Option("-o", "--output", help="Output file (default: stdout)")
    ] = None,
    agent: Annotated[str | None, typer.Option(help="Filter by agent name")] = None,
    run_id: Annotated[str | None, typer.Option(help="Filter by run ID")] = None,
    trigger_type: Annotated[str | None, typer.Option(help="Filter by trigger type")] = None,
    since: Annotated[str | None, typer.Option(help="Filter: timestamp >= ISO string")] = None,
    until: Annotated[str | None, typer.Option(help="Filter: timestamp <= ISO string")] = None,
    limit: Annotated[int, typer.Option(help="Max records to return")] = 1000,
    audit_db: Annotated[Path | None, typer.Option(help="Path to audit database")] = None,
) -> None:
    """Export audit records as JSON or CSV."""
    from initrunner.audit.logger import DEFAULT_DB_PATH
    from initrunner.audit.logger import AuditLogger as _AuditLogger

    db_path = audit_db or DEFAULT_DB_PATH
    if not db_path.exists():
        console.print(f"[red]Error:[/red] Audit database not found at {db_path}")
        raise typer.Exit(1)

    if format not in ("json", "csv"):
        console.print(f"[red]Error:[/red] Unknown format '{format}'. Use: json, csv")
        raise typer.Exit(1)

    with _AuditLogger(db_path) as logger:
        records = logger.query(
            agent_name=agent,
            run_id=run_id,
            trigger_type=trigger_type,
            since=since,
            until=until,
            limit=limit,
        )

    from initrunner.audit.logger import _RECORD_FIELDS, record_to_dict

    if format == "json":
        data = [record_to_dict(r, parse_trigger_metadata=True) for r in records]
        text = json.dumps(data, indent=2)
    else:
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=_RECORD_FIELDS)
        writer.writeheader()
        for r in records:
            writer.writerow(record_to_dict(r))
        text = buf.getvalue()

    if output is not None:
        output.write_text(text)
        console.print(f"[green]Exported[/green] {len(records)} record(s) to {output}.")
    else:
        sys.stdout.write(text)
