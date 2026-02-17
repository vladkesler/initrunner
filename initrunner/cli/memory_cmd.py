"""Memory commands: clear, export, list, consolidate."""

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
    memory_type: Annotated[
        str | None,
        typer.Option("--type", help="Clear only this memory type (episodic, semantic, procedural)"),
    ] = None,
    force: Annotated[bool, typer.Option("--force", help="Skip confirmation")] = False,
) -> None:
    """Clear memory store for an agent."""
    from initrunner.agent.memory_ops import clear_memories

    role = load_role_or_exit(role_file)

    if role.spec.memory is None:
        console.print("[red]Error:[/red] No memory config in role definition.")
        raise typer.Exit(1)

    mt_filter = None
    if memory_type:
        from initrunner.stores.base import MemoryType

        try:
            mt_filter = MemoryType(memory_type)
        except ValueError:
            console.print(
                f"[red]Error:[/red] Invalid type '{memory_type}'. "
                "Use: episodic, semantic, procedural"
            )
            raise typer.Exit(1) from None

    if not force:
        what = "sessions" if sessions_only else ("memories" if memories_only else "all memory data")
        if mt_filter:
            what = f"{mt_filter} memories"
        confirm = typer.confirm(f"Clear {what} for {role.metadata.name}?")
        if not confirm:
            console.print("Aborted.")
            return

    if not clear_memories(
        role, sessions_only=sessions_only, memories_only=memories_only, memory_type=mt_filter
    ):
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


@app.command("list")
def memory_list(
    role_file: Annotated[Path, typer.Argument(help="Path to role.yaml")],
    memory_type: Annotated[
        str | None,
        typer.Option("--type", help="Filter by memory type (episodic, semantic, procedural)"),
    ] = None,
    category: Annotated[str | None, typer.Option("--category", help="Filter by category")] = None,
    limit: Annotated[int, typer.Option("--limit", help="Maximum number of results")] = 20,
) -> None:
    """List memories for an agent."""
    from initrunner.services import list_memories_sync

    role = load_role_or_exit(role_file)

    if role.spec.memory is None:
        console.print("[red]Error:[/red] No memory config in role definition.")
        raise typer.Exit(1)

    mt_filter = None
    if memory_type:
        from initrunner.stores.base import MemoryType

        try:
            mt_filter = MemoryType(memory_type)
        except ValueError:
            console.print(
                f"[red]Error:[/red] Invalid type '{memory_type}'. "
                "Use: episodic, semantic, procedural"
            )
            raise typer.Exit(1) from None

    memories = list_memories_sync(role, category=category, limit=limit, memory_type=mt_filter)

    if not memories:
        console.print("No memories found.")
        return

    for mem in memories:
        preview = mem.content[:100]
        console.print(
            f"[dim]#{mem.id}[/dim] [{mem.memory_type}:{mem.category}] ({mem.created_at}) {preview}"
        )

    console.print(f"\n[dim]{len(memories)} memories shown.[/dim]")


@app.command("consolidate")
def memory_consolidate(
    role_file: Annotated[Path, typer.Argument(help="Path to role.yaml")],
) -> None:
    """Manually run memory consolidation (extract semantic facts from episodes)."""
    role = load_role_or_exit(role_file)

    if role.spec.memory is None:
        console.print("[red]Error:[/red] No memory config in role definition.")
        raise typer.Exit(1)

    from initrunner.stores.factory import open_memory_store

    with open_memory_store(role.spec.memory, role.metadata.name) as store:
        if store is None:
            console.print("No memory store found.")
            return

        from initrunner.agent.memory_consolidation import maybe_consolidate

        with console.status("Consolidating episodic memories...", spinner="dots"):
            created = maybe_consolidate(store, role, force=True)

    if created > 0:
        console.print(f"[green]Created[/green] {created} semantic memories from episodic data.")
    else:
        console.print("No episodic memories to consolidate.")
