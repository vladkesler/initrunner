"""Team execution dispatch."""

from __future__ import annotations

from pathlib import Path

import typer

from initrunner.cli._helpers import console, create_audit_logger


def _display_team_result(team_result: object) -> None:
    """Display team run results."""
    from rich.markdown import Markdown
    from rich.panel import Panel

    from initrunner.team.results import TeamResult

    tr: TeamResult = team_result  # type: ignore[assignment]

    for name, agent_result in zip(tr.agent_names, tr.agent_results, strict=True):
        status = "[green]OK[/green]" if agent_result.success else "[red]FAIL[/red]"
        console.print(
            f"  {status} {name}  "
            f"{agent_result.tokens_in}in/{agent_result.tokens_out}out  "
            f"{agent_result.duration_ms}ms"
        )

    if tr.success and tr.final_output:
        subtitle = (
            f"tokens: {tr.total_tokens_in}in/{tr.total_tokens_out}out | {tr.total_duration_ms}ms"
        )
        console.print(
            Panel(
                Markdown(tr.final_output),
                title="Team Result",
                subtitle=subtitle,
                border_style="green",
            )
        )
    elif not tr.success:
        console.print(Panel(f"[red]{tr.error}[/red]", title="Team Error", border_style="red"))


def _run_team(
    team_file: Path,
    prompt: str | None,
    dry_run: bool,
    no_audit: bool,
) -> None:
    """Run a team YAML file."""
    if not prompt:
        console.print("[red]Error:[/red] Team mode requires --prompt (-p).")
        raise typer.Exit(1)

    from initrunner.team.loader import TeamLoadError, load_team
    from initrunner.team.runner import run_team_dispatch

    try:
        team = load_team(team_file)
    except TeamLoadError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1) from None

    audit_logger = create_audit_logger(None, no_audit)

    dry_run_model = None
    if dry_run:
        from pydantic_ai.models.test import TestModel

        dry_run_model = TestModel(custom_output_text="[dry-run] Simulated response.", call_tools=[])

    persona_names = list(team.spec.personas.keys())
    console.print(f"[bold]Team mode[/bold] -- team: [cyan]{team.metadata.name}[/cyan]")
    console.print(f"  Strategy: {team.spec.strategy}")
    console.print(f"  Personas: {', '.join(persona_names)}")
    if team.spec.shared_memory.enabled:
        console.print("  Shared memory: enabled")
    if team.spec.shared_documents.enabled:
        n_sources = len(team.spec.shared_documents.sources)
        console.print(f"  Shared documents: enabled ({n_sources} sources)")
    console.print()

    strategy = team.spec.strategy
    status_text = (
        "[dim]Running team pipeline (parallel)...[/dim]"
        if strategy == "parallel"
        else "[dim]Running team pipeline...[/dim]"
    )
    from initrunner.runner.display import _make_prefixed_tool_event_printer

    tool_printer = _make_prefixed_tool_event_printer()

    with console.status(status_text) as status:
        result = run_team_dispatch(
            team,
            prompt,
            team_dir=team_file.parent,
            audit_logger=audit_logger,
            dry_run_model=dry_run_model,
            on_persona_start=lambda name: status.update(f"[dim]Running persona: {name}...[/dim]"),
            on_tool_event=tool_printer,
        )

    _display_team_result(result)

    if audit_logger is not None:
        audit_logger.close()

    if not result.success:
        raise typer.Exit(1)
