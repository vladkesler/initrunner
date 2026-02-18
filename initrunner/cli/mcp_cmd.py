"""MCP commands: list-tools."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from initrunner.cli._helpers import console

app = typer.Typer(help="MCP server introspection.")


@app.command("list-tools")
def list_tools(
    role_file: Annotated[Path, typer.Argument(help="Path to role.yaml")],
    index: Annotated[
        int | None,
        typer.Option("--index", "-i", help="Target a specific MCP tool entry (0-based)"),
    ] = None,
) -> None:
    """List tools available from MCP servers configured in a role."""
    from rich.table import Table

    from initrunner.services.operations import list_mcp_tools_sync

    try:
        results = list_mcp_tools_sync(role_file, index=index)
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1) from None

    if not results:
        console.print("No MCP tools found in role definition.")
        return

    table = Table(title="MCP Tools")
    table.add_column("Server", style="cyan")
    table.add_column("Tool", style="green")
    table.add_column("Description")

    for server, name, description in results:
        table.add_row(server, name, description)

    console.print(table)
