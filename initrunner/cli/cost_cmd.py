"""Cost analytics commands: report, summary, by-model."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from initrunner.cli._helpers import console
from initrunner.cli._options import AuditDbOption

app = typer.Typer(help="Analyze agent costs and token usage.")


def _fmt_cost(cost: float | None) -> str:
    if cost is None:
        return "N/A"
    if cost < 0.01:
        return f"${cost:.4f}"
    return f"${cost:.2f}"


def _check_db(audit_db: AuditDbOption) -> Path:
    from initrunner.audit.logger import DEFAULT_DB_PATH

    db_path = Path(audit_db or DEFAULT_DB_PATH)
    if not db_path.exists():
        console.print(f"[red]Error:[/red] Audit database not found at {db_path}")
        console.print(
            "[dim]Hint:[/dim] Run an agent first to create the audit log,"
            " or pass [bold]--audit-db[/bold]."
        )
        raise typer.Exit(1)
    return db_path


@app.command("report")
def cost_report(
    agent: Annotated[str | None, typer.Option(help="Filter by agent name")] = None,
    since: Annotated[str | None, typer.Option(help="Filter: timestamp >= ISO string")] = None,
    until: Annotated[str | None, typer.Option(help="Filter: timestamp <= ISO string")] = None,
    audit_db: AuditDbOption = None,
) -> None:
    """Cost breakdown by agent."""
    from rich.table import Table

    from initrunner.services.cost import cost_report_sync

    db_path = _check_db(audit_db)
    report = cost_report_sync(agent_name=agent, since=since, until=until, audit_db=db_path)

    if not report.entries:
        console.print("[dim]No audit records found.[/dim]")
        return

    table = Table(title="Cost Report")
    table.add_column("Agent", style="cyan")
    table.add_column("Requests", justify="right")
    table.add_column("Tokens In", justify="right")
    table.add_column("Tokens Out", justify="right")
    table.add_column("Est. Cost", justify="right", style="green")
    table.add_column("Avg/Request", justify="right")

    for entry in report.entries:
        table.add_row(
            entry.agent_name,
            f"{entry.run_count:,}",
            f"{entry.tokens_in:,}",
            f"{entry.tokens_out:,}",
            _fmt_cost(entry.total_cost_usd),
            _fmt_cost(entry.avg_cost_per_run),
        )

    console.print(table)
    total_label = _fmt_cost(report.total_cost_usd)
    console.print(f"\nTotal: {report.total_runs:,} requests, {total_label} estimated")


@app.command("summary")
def cost_summary(
    audit_db: AuditDbOption = None,
) -> None:
    """Overall cost summary across all agents."""
    from rich.table import Table

    from initrunner.services.cost import cost_summary_sync

    db_path = _check_db(audit_db)
    summary = cost_summary_sync(audit_db=db_path)

    # Period totals
    console.print("[bold]Cost Summary[/bold]\n")
    console.print(f"  Today:      {_fmt_cost(summary.today)}")
    console.print(f"  This week:  {_fmt_cost(summary.this_week)}")
    console.print(f"  This month: {_fmt_cost(summary.this_month)}")
    console.print(f"  All time:   {_fmt_cost(summary.all_time)}")

    # Top agents
    if summary.top_agents:
        console.print()
        table = Table(title="Top 5 Agents by Cost")
        table.add_column("Agent", style="cyan")
        table.add_column("Requests", justify="right")
        table.add_column("Est. Cost", justify="right", style="green")

        for entry in summary.top_agents:
            table.add_row(
                entry.agent_name,
                f"{entry.run_count:,}",
                _fmt_cost(entry.total_cost_usd),
            )
        console.print(table)

    # Daily trend (last 7 days)
    if summary.daily_trend:
        recent = summary.daily_trend[-7:]
        console.print()
        table = Table(title="Last 7 Days")
        table.add_column("Date")
        table.add_column("Requests", justify="right")
        table.add_column("Est. Cost", justify="right", style="green")

        for day in recent:
            table.add_row(day.date, f"{day.run_count:,}", _fmt_cost(day.total_cost_usd))
        console.print(table)


@app.command("by-model")
def cost_by_model(
    since: Annotated[str | None, typer.Option(help="Filter: timestamp >= ISO string")] = None,
    until: Annotated[str | None, typer.Option(help="Filter: timestamp <= ISO string")] = None,
    audit_db: AuditDbOption = None,
) -> None:
    """Cost breakdown by model and provider."""
    from rich.table import Table

    from initrunner.services.cost import cost_by_model_sync

    db_path = _check_db(audit_db)
    entries = cost_by_model_sync(since=since, until=until, audit_db=db_path)

    if not entries:
        console.print("[dim]No audit records found.[/dim]")
        return

    table = Table(title="Cost by Model")
    table.add_column("Model", style="cyan")
    table.add_column("Provider")
    table.add_column("Requests", justify="right")
    table.add_column("Tokens In", justify="right")
    table.add_column("Tokens Out", justify="right")
    table.add_column("Est. Cost", justify="right", style="green")

    for entry in entries:
        table.add_row(
            entry.model,
            entry.provider,
            f"{entry.run_count:,}",
            f"{entry.tokens_in:,}",
            f"{entry.tokens_out:,}",
            _fmt_cost(entry.total_cost_usd),
        )
    console.print(table)


@app.command("estimate")
def cost_estimate(
    role_path: Annotated[Path, typer.Argument(help="Path to role YAML file")],
    prompt_tokens: Annotated[
        int | None, typer.Option("--prompt-tokens", help="Override assumed user prompt tokens")
    ] = None,
) -> None:
    """Estimate per-run cost for a role before deploying."""
    from pathlib import Path as _P

    from rich.panel import Panel
    from rich.table import Table

    from initrunner.services.cost import estimate_role_cost_sync

    role_path = _P(role_path)
    if not role_path.exists():
        console.print(f"[red]Error:[/red] Role file not found: {role_path}")
        raise typer.Exit(1)

    try:
        est = estimate_role_cost_sync(role_path, prompt_tokens=prompt_tokens)
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1) from None

    # Per-run table
    table = Table(title="Cost Estimate", show_header=True)
    table.add_column("Metric", style="cyan")
    table.add_column("Value", justify="right")

    model_label = f"{est.provider}:{est.model}" if est.model_resolved else "(unresolved)"
    table.add_row("Model", model_label)
    table.add_row("Est. input tokens", f"{est.estimated_input_tokens:,}")
    table.add_row("Est. output tokens (typical)", f"{est.estimated_output_tokens_typical:,}")
    table.add_row("Est. output tokens (max)", f"{est.estimated_output_tokens_max:,}")
    table.add_row("Per-run cost (typical)", _fmt_cost(est.per_run_typical))
    table.add_row("Per-run cost (max)", _fmt_cost(est.per_run_max))

    if est.trigger_runs_per_day is not None:
        table.add_row("Trigger firings/day", f"{est.trigger_runs_per_day}")
        table.add_row("Daily estimate", _fmt_cost(est.daily_estimate))
        table.add_row("Monthly estimate", _fmt_cost(est.monthly_estimate))

    console.print(table)

    # Assumptions
    if est.assumptions:
        lines = "\n".join(f"  - {a}" for a in est.assumptions)
        console.print(Panel(lines, title="Assumptions", border_style="dim"))
