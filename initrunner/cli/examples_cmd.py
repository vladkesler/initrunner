"""Examples sub-commands: list, show, copy."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from initrunner.cli._helpers import console

app = typer.Typer(help="Browse and copy bundled examples.")


@app.command("list")
def examples_list(
    category: Annotated[
        str | None,
        typer.Option("--category", "-c", help="Filter by category: role, compose, skill"),
    ] = None,
    tag: Annotated[
        str | None,
        typer.Option("--tag", "-t", help="Filter by tag"),
    ] = None,
) -> None:
    """List available examples."""
    from rich.table import Table

    from initrunner.examples import list_examples

    entries = list_examples(category=category, tag=tag)

    if not entries:
        console.print("No examples found matching the given filters.")
        return

    table = Table(title="Available Examples")
    table.add_column("Name", style="cyan")
    table.add_column("Category", style="magenta")
    table.add_column("Description")
    table.add_column("Difficulty", style="yellow")
    table.add_column("Tags", style="dim")

    for entry in entries:
        table.add_row(
            entry.name,
            entry.category,
            entry.description,
            entry.difficulty,
            ", ".join(entry.tags),
        )

    console.print(table)


@app.command("show")
def examples_show(
    name: Annotated[str, typer.Argument(help="Name of the example to show")],
) -> None:
    """Show the primary file of an example with syntax highlighting."""
    from rich.panel import Panel
    from rich.syntax import Syntax

    from initrunner.examples import ExampleNotFoundError, get_example

    try:
        entry = get_example(name)
    except ExampleNotFoundError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1) from None

    # Determine syntax lexer from file extension
    lexer = "yaml"
    if entry.primary_file.endswith(".md"):
        lexer = "markdown"

    syntax = Syntax(entry.primary_content, lexer, theme="monokai", line_numbers=True)
    panel = Panel(
        syntax,
        title=f"{entry.name} ({entry.category})",
        subtitle=entry.primary_file,
    )
    console.print(panel)

    if entry.multi_file:
        console.print(
            f"\n[dim]This is a multi-file example with {len(entry.files)} files. "
            f"Use [bold]initrunner examples copy {entry.name}[/bold] to get all files.[/dim]"
        )


@app.command("copy")
def examples_copy(
    name: Annotated[str, typer.Argument(help="Name of the example to copy")],
    output: Annotated[
        Path,
        typer.Option("--output", "-o", help="Output directory (default: current dir)"),
    ] = Path("."),
) -> None:
    """Copy example files to a directory."""
    from initrunner.examples import (
        ExampleDownloadError,
        ExampleNotFoundError,
        copy_example,
    )

    try:
        written = copy_example(name, output)
    except ExampleNotFoundError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1) from None
    except FileExistsError as e:
        console.print(f"[red]Error:[/red] {e}")
        console.print(
            "[dim]Remove existing files first or choose a different output directory.[/dim]"
        )
        raise typer.Exit(1) from None
    except ExampleDownloadError as e:
        console.print(f"[red]Download error:[/red] {e}")
        raise typer.Exit(1) from None

    console.print(f"[green]Copied {len(written)} file(s):[/green]")
    for path in written:
        console.print(f"  {path}")

    # Print next-step hints
    primary = written[0] if written else None
    if primary and primary.suffix in (".yaml", ".yml"):
        console.print("\n[dim]Next steps:[/dim]")
        console.print(f"  [bold]initrunner validate {primary}[/bold]")
        console.print(f"  [bold]initrunner run {primary}[/bold]")
