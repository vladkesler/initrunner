"""Pipeline execution dispatch."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.table import Table

from initrunner.cli._helpers import console, create_audit_logger


def _display_pipeline_dry_run(pipe: object, variables: dict[str, str]) -> None:
    from initrunner.pipeline.schema import PipelineDefinition

    p: PipelineDefinition = pipe  # type: ignore[assignment]

    table = Table(title=f"Pipeline: {p.metadata.name}")
    table.add_column("Step", style="cyan")
    table.add_column("Mode")
    table.add_column("Source")
    table.add_column("Depends On")
    table.add_column("Condition")
    table.add_column("Output")

    for step in p.spec.steps:
        source = step.role_file or step.url or ""
        deps = ", ".join(step.depends_on) if step.depends_on else "(none)"
        cond = step.condition or "(always)"
        table.add_row(step.name, step.mode, source, deps, cond, step.output_format)

    console.print(table)

    if variables:
        console.print("\n[bold]Variables:[/bold]")
        for k, v in variables.items():
            console.print(f"  {k} = {v}")

    console.print(f"\n[bold]Strategy:[/bold] {p.spec.error_strategy}")
    console.print(f"[bold]Max parallel:[/bold] {p.spec.max_parallel}")
    console.print("\n[green]Pipeline definition is valid.[/green]")


def _display_pipeline_result(result: object) -> None:
    from initrunner.pipeline.executor import PipelineResult

    r: PipelineResult = result  # type: ignore[assignment]

    table = Table(title=f"Pipeline: {r.pipeline_name} ({r.pipeline_id})")
    table.add_column("Step", style="cyan")
    table.add_column("Status")
    table.add_column("Duration")
    table.add_column("Output (preview)")

    for sr in r.step_results:
        if sr.skipped:
            status = f"[dim]SKIP[/dim] ({sr.skip_reason})"
        elif sr.success:
            status = "[green]PASS[/green]"
        else:
            status = f"[red]FAIL[/red] ({sr.error})"

        duration = f"{sr.duration_ms}ms"
        preview = (sr.output[:80] + "...") if len(sr.output) > 80 else sr.output
        table.add_row(sr.name, status, duration, preview)

    console.print(table)
    total = f"[bold]Total: {r.duration_ms}ms[/bold]"
    if r.success:
        console.print(f"\n{total} [green]Pipeline succeeded[/green]")
    else:
        console.print(f"\n{total} [red]Pipeline failed[/red]")


def _dispatch_pipeline(
    pipeline_file: Path,
    var: list[str] | None,
    dry_run: bool,
    audit_db: Path | None,
    no_audit: bool,
) -> None:
    """Run a pipeline file."""
    from initrunner.pipeline.loader import PipelineLoadError, load_pipeline

    try:
        pipe = load_pipeline(pipeline_file)
    except PipelineLoadError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1) from None

    variables: dict[str, str] = {}
    for v in var or []:
        if "=" not in v:
            console.print(f"[red]Error:[/red] Invalid variable format: '{v}'. Use key=value.")
            raise typer.Exit(1)
        key, value = v.split("=", 1)
        variables[key] = value

    if dry_run:
        _display_pipeline_dry_run(pipe, variables)
        return

    audit_logger = create_audit_logger(audit_db, no_audit)

    try:
        from initrunner.pipeline.executor import run_pipeline

        result = run_pipeline(
            pipe,
            variables=variables,
            audit_logger=audit_logger,
            base_dir=pipeline_file.parent,
        )
        _display_pipeline_result(result)

        if not result.success:
            raise typer.Exit(1)
    finally:
        if audit_logger is not None:
            audit_logger.close()
