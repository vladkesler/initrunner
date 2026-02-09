"""Memory commands: clear, export."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from initrunner.cli._helpers import console, load_role_or_exit

app = typer.Typer(help="Manage agent memory.")


@app.command("clear")
def memory_clear(
    role_file: Annotated[Path, typer.Argument(help="Path to role.yaml")],
    sessions_only: Annotated[bool, typer.Option(help="Only clear sessions")] = False,
    memories_only: Annotated[bool, typer.Option(help="Only clear memories")] = False,
    force: Annotated[bool, typer.Option("--force", help="Skip confirmation")] = False,
) -> None:
    """Clear memory store for an agent."""
    from initrunner.agent.memory_ops import clear_memories

    role = load_role_or_exit(role_file)

    if role.spec.memory is None:
        console.print("[red]Error:[/red] No memory config in role definition.")
        raise typer.Exit(1)

    if not force:
        what = "sessions" if sessions_only else ("memories" if memories_only else "all memory data")
        confirm = typer.confirm(f"Clear {what} for {role.metadata.name}?")
        if not confirm:
            console.print("Aborted.")
            return

    if not clear_memories(role, sessions_only=sessions_only, memories_only=memories_only):
        console.print("No memory store found.")
        return

    console.print(f"[green]Cleared[/green] memory for {role.metadata.name}.")


@app.command("export")
def memory_export(
    role_file: Annotated[Path, typer.Argument(help="Path to role.yaml")],
    output: Annotated[Path, typer.Option("-o", "--output", help="Output JSON file")] = Path(
        "memories.json"
    ),
) -> None:
    """Export memories to JSON."""
    from initrunner.agent.memory_ops import export_memories

    role = load_role_or_exit(role_file)

    if role.spec.memory is None:
        console.print("[red]Error:[/red] No memory config in role definition.")
        raise typer.Exit(1)

    data = export_memories(role)
    if not data:
        console.print("No memory store found.")
        return

    output.write_text(json.dumps(data, indent=2))
    console.print(f"[green]Exported[/green] {len(data)} memories to {output}.")
