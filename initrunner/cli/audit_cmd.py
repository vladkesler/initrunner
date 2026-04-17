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
from initrunner.cli._options import AuditDbOption

app = typer.Typer(help="Inspect and export audit records.")


@app.command("prune")
def audit_prune(
    retention_days: Annotated[
        int, typer.Option(help="Delete records older than this many days")
    ] = 90,
    max_records: Annotated[int, typer.Option(help="Maximum records to keep")] = 100_000,
    audit_db: AuditDbOption = None,
) -> None:
    """Prune old audit records."""
    from initrunner.audit.logger import DEFAULT_DB_PATH
    from initrunner.services.operations import audit_prune_sync

    db_path = Path(audit_db or DEFAULT_DB_PATH)
    if not db_path.exists():
        console.print(f"[red]Error:[/red] Audit database not found at {db_path}")
        console.print(
            "[dim]Hint:[/dim] Run an agent first to create the audit log,"
            " or pass [bold]--audit-db[/bold]."
        )
        raise typer.Exit(1)

    deleted = audit_prune_sync(
        retention_days=retention_days, max_records=max_records, audit_db=db_path
    )

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
    audit_db: AuditDbOption = None,
) -> None:
    """Export audit records as JSON or CSV."""
    from initrunner.audit.logger import DEFAULT_DB_PATH
    from initrunner.services.operations import query_audit_sync

    db_path = Path(audit_db or DEFAULT_DB_PATH)
    if not db_path.exists():
        console.print(f"[red]Error:[/red] Audit database not found at {db_path}")
        console.print(
            "[dim]Hint:[/dim] Run an agent first to create the audit log,"
            " or pass [bold]--audit-db[/bold]."
        )
        raise typer.Exit(1)

    if format not in ("json", "csv"):
        console.print(f"[red]Error:[/red] Unknown format '{format}'. Use: json, csv")
        raise typer.Exit(1)

    records = query_audit_sync(
        agent_name=agent,
        run_id=run_id,
        trigger_type=trigger_type,
        since=since,
        until=until,
        limit=limit,
        audit_db=db_path,
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


@app.command("verify-chain")
def audit_verify_chain(audit_db: AuditDbOption = None) -> None:
    """Verify the HMAC-signed audit chain. Exits non-zero on any break."""
    from rich.table import Table

    from initrunner.audit.logger import DEFAULT_DB_PATH
    from initrunner.services.operations import verify_audit_chain_sync

    db_path = Path(audit_db or DEFAULT_DB_PATH)
    if not db_path.exists():
        console.print(f"[red]Error:[/red] Audit database not found at {db_path}")
        raise typer.Exit(1)

    result = verify_audit_chain_sync(audit_db=db_path)

    tip_hash_short = result.last_verified_hash[:16] + "..." if result.last_verified_hash else "-"

    table = Table(show_header=False, box=None, pad_edge=False)
    table.add_column(style="dim")
    table.add_column()
    table.add_row("Total rows", str(result.total_rows))
    table.add_row("Unsigned (legacy)", str(result.unsigned_legacy_rows))
    table.add_row("Verified", str(result.verified_rows))
    table.add_row("Tip id", str(result.last_verified_id) if result.last_verified_id else "-")
    table.add_row("Tip hash", tip_hash_short)
    table.add_row("Pruned gaps", str(len(result.pruned_gaps)))
    console.print(table)

    if result.ok:
        console.print("[green]Chain verified.[/green]")
        return

    reason = result.first_break_reason or "unknown"
    if reason in ("key_missing", "key_invalid"):
        console.print(f"[red]Cannot verify:[/red] {reason}")
        if reason == "key_missing":
            from initrunner.config import get_audit_hmac_key_path

            console.print(
                "[dim]Hint:[/dim] set [bold]INITRUNNER_AUDIT_HMAC_KEY[/bold] "
                f"(64-char hex) or place the 32-byte key at "
                f"[bold]{get_audit_hmac_key_path()}[/bold]."
            )
    else:
        console.print(f"[red]Chain broken[/red] at id {result.first_break_id}: {reason}")
    raise typer.Exit(1)
