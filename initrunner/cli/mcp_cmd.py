"""MCP commands: list-tools, serve."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from initrunner.cli._helpers import console

app = typer.Typer(help="MCP server introspection and gateway.")


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


_VALID_TRANSPORTS = {"stdio", "sse", "streamable-http"}


@app.command("serve")
def mcp_serve(
    role_files: Annotated[
        list[Path], typer.Argument(help="Role YAML files to expose as MCP tools")
    ],
    transport: Annotated[
        str, typer.Option("--transport", "-t", help="Transport: stdio, sse, streamable-http")
    ] = "stdio",
    host: Annotated[str, typer.Option(help="Host to bind to (sse/http)")] = "127.0.0.1",
    port: Annotated[int, typer.Option(help="Port to listen on (sse/http)")] = 8080,
    server_name: Annotated[str, typer.Option(help="MCP server name")] = "initrunner",
    pass_through: Annotated[
        bool, typer.Option("--pass-through", help="Also expose agent MCP tools directly")
    ] = False,
    audit_db: Annotated[Path | None, typer.Option(help="Path to audit database")] = None,
    no_audit: Annotated[bool, typer.Option(help="Disable audit logging")] = False,
    skill_dir: Annotated[
        Path | None, typer.Option("--skill-dir", help="Extra skill search directory")
    ] = None,
) -> None:
    """Expose InitRunner agents as an MCP server."""
    from initrunner.cli._helpers import create_audit_logger, resolve_skill_dirs
    from initrunner.mcp.gateway import build_mcp_gateway, run_mcp_gateway

    # All output goes to stderr to keep stdout clean for stdio transport
    err_console = Console(stderr=True)

    # Validate transport
    if transport not in _VALID_TRANSPORTS:
        err_console.print(f"[red]Error:[/red] Unknown transport: {transport!r}")
        err_console.print(f"Expected one of: {', '.join(sorted(_VALID_TRANSPORTS))}")
        raise typer.Exit(1)

    # Validate role files exist
    for rf in role_files:
        if not rf.exists():
            err_console.print(f"[red]Error:[/red] Role file not found: {rf}")
            raise typer.Exit(1)

    audit_logger = create_audit_logger(audit_db, no_audit)
    extra_skill_dirs = resolve_skill_dirs(skill_dir)

    try:
        mcp = build_mcp_gateway(
            role_files,
            server_name=server_name,
            audit_logger=audit_logger,
            pass_through=pass_through,
            extra_skill_dirs=extra_skill_dirs,
        )
    except Exception as e:
        err_console.print(f"[red]Error:[/red] {e}")
        if audit_logger is not None:
            audit_logger.close()
        raise typer.Exit(1) from None

    try:
        err_console.print(f"[bold]MCP Gateway:[/bold] {server_name}")
        err_console.print(f"  Transport: {transport}")
        for rf in role_files:
            err_console.print(f"  Role: {rf}")
        if transport != "stdio":
            err_console.print(f"  Endpoint: {host}:{port}")

        run_mcp_gateway(mcp, transport=transport, host=host, port=port)
    except Exception as e:
        err_console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1) from None
    finally:
        if audit_logger is not None:
            audit_logger.close()
