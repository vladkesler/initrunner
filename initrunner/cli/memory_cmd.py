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
    role_file: Annotated[Path, typer.Argument(help="Agent directory or role YAML file")],
    what: Annotated[
        str,
        typer.Option("--what", help="What to clear: sessions, memories, or all"),
    ] = "all",
    memory_type: Annotated[
        str | None,
        typer.Option("--type", help="Clear only this memory type (episodic, semantic, procedural)"),
    ] = None,
    force: Annotated[bool, typer.Option("--force", help="Skip confirmation")] = False,
) -> None:
    """Clear memory store for an agent."""
    from initrunner.services.memory import clear_memories_sync

    role = load_role_or_exit(role_file)

    if role.spec.memory is None:
        console.print("[red]Error:[/red] No memory config in role definition.")
        raise typer.Exit(1)

    if what not in ("sessions", "memories", "all"):
        console.print("[red]Error:[/red] --what must be sessions, memories, or all.")
        raise typer.Exit(1)

    if what == "sessions" and memory_type is not None:
        console.print("[red]Error:[/red] --type cannot be used with --what sessions.")
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
        label = what if what != "all" else "all memory data"
        if mt_filter:
            label = f"{mt_filter} memories"
        confirm = typer.confirm(f"Clear {label} for {role.metadata.name}?")
        if not confirm:
            console.print("Aborted.")
            return

    if not clear_memories_sync(role, what=what, memory_type=mt_filter):
        console.print("No memory store found.")
        return

    console.print(f"[green]Cleared[/green] memory for {role.metadata.name}.")


@app.command("export")
def memory_export(
    role_file: Annotated[Path, typer.Argument(help="Agent directory or role YAML file")],
    output: Annotated[Path, typer.Option("-o", "--output", help="Output JSON file")] = Path(
        "memories.json"
    ),
) -> None:
    """Export memories to JSON."""
    from initrunner.services.memory import export_memories_sync

    role = load_role_or_exit(role_file)

    if role.spec.memory is None:
        console.print("[red]Error:[/red] No memory config in role definition.")
        raise typer.Exit(1)

    data = export_memories_sync(role)
    if not data:
        console.print("No memory store found.")
        return

    output.write_text(json.dumps(data, indent=2))
    console.print(f"[green]Exported[/green] {len(data)} memories to {output}.")


@app.command("list")
def memory_list(
    role_file: Annotated[Path, typer.Argument(help="Agent directory or role YAML file")],
    memory_type: Annotated[
        str | None,
        typer.Option("--type", help="Filter by memory type (episodic, semantic, procedural)"),
    ] = None,
    category: Annotated[str | None, typer.Option("--category", help="Filter by category")] = None,
    limit: Annotated[int, typer.Option("--limit", help="Maximum number of results")] = 20,
) -> None:
    """List memories for an agent."""
    from initrunner.services.memory import list_memories_sync

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


@app.command("import")
def memory_import(
    role_file: Annotated[Path, typer.Argument(help="Agent directory or role YAML file")],
    input_file: Annotated[Path, typer.Argument(help="JSON file to import")],
) -> None:
    """Import memories from a JSON file (re-embeds content using the role's embedding config)."""
    from initrunner.agent.loader import _load_dotenv
    from initrunner.cli._helpers import resolve_role_path
    from initrunner.services.memory import import_memories_sync

    role_file = resolve_role_path(role_file)
    role = load_role_or_exit(role_file)

    if role.spec.memory is None:
        console.print("[red]Error:[/red] No memory config in role definition.")
        raise typer.Exit(1)

    if not input_file.exists():
        console.print(f"[red]Error:[/red] File not found: {input_file}")
        raise typer.Exit(1)

    try:
        data = json.loads(input_file.read_text())
    except json.JSONDecodeError as exc:
        console.print(f"[red]Error:[/red] Invalid JSON: {exc}")
        raise typer.Exit(1) from None

    if not isinstance(data, list):
        console.print("[red]Error:[/red] Expected a JSON array of memory objects.")
        raise typer.Exit(1)

    # Load .env from role directory so embedding API keys are available
    _load_dotenv(role_file.parent)

    try:
        with console.status("Importing memories...", spinner="dots"):
            count = import_memories_sync(role, data)
    except ValueError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1) from None

    console.print(f"[green]Imported[/green] {count} memories into {role.metadata.name}.")


@app.command("consolidate")
def memory_consolidate(
    role_file: Annotated[Path, typer.Argument(help="Agent directory or role YAML file")],
) -> None:
    """Manually run memory consolidation (extract semantic facts from episodes)."""
    role = load_role_or_exit(role_file)

    if role.spec.memory is None:
        console.print("[red]Error:[/red] No memory config in role definition.")
        raise typer.Exit(1)

    from initrunner.services.memory import consolidate_memories_sync

    with console.status("Consolidating episodic memories...", spinner="dots"):
        created = consolidate_memories_sync(role, force=True)

    if created > 0:
        console.print(f"[green]Created[/green] {created} semantic memories from episodic data.")
    else:
        console.print("No episodic memories to consolidate.")
