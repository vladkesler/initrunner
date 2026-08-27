"""Starter agent listing and save-to-local helpers."""

from __future__ import annotations

from initrunner.cli._helpers import console


def _show_starter_listing() -> None:
    """Render a Rich table of available starter agents."""
    from rich.table import Table

    from initrunner.services.starters import check_prerequisites, list_starters

    starters = list_starters()
    if not starters:
        console.print("[dim]No starter agents found.[/dim]")
        return

    table = Table(title="Starter Agents", show_lines=False, pad_edge=False)
    table.add_column("Name", style="cyan", no_wrap=True)
    table.add_column("Kind", style="dim")
    table.add_column("Description")
    table.add_column("Features", style="green")
    table.add_column("Status")

    from initrunner.services.starters import starter_content

    for entry in starters:
        errors, _warnings = check_prerequisites(entry)
        if errors:
            status = f"[yellow]{errors[0]}[/yellow]"
        elif starter_content(entry).kind == "bundled":
            status = "[green]Ready (samples)[/green]"
        else:
            status = "[green]Ready[/green]"

        desc = entry.description
        if len(desc) > 50:
            desc = desc[:47] + "..."

        table.add_row(
            entry.slug,
            entry.kind,
            desc,
            " ".join(entry.features),
            status,
        )

    console.print()
    console.print(table)
    console.print()
    console.print("[dim]Usage:[/dim]")
    console.print("  initrunner run <name>              Run interactively")
    console.print('  initrunner run <name> -p "..."      Single-shot with prompt')
    console.print("  initrunner examples copy <name>    Copy to a directory to customize")
    console.print()
