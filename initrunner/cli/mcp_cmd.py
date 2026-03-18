"""MCP commands: list-tools, serve, toolkit."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from initrunner.cli._helpers import console
from initrunner.cli._options import AuditDbOption, NoAuditOption, SkillDirOption

app = typer.Typer(help="MCP server introspection, gateway, and toolkit.")


@app.command("list-tools")
def list_tools(
    role_file: Annotated[Path, typer.Argument(help="Agent directory or role YAML file")],
    index: Annotated[
        int | None,
        typer.Option("--index", "-i", help="Target a specific MCP tool entry (0-based)"),
    ] = None,
) -> None:
    """List tools available from MCP servers configured in a role."""
    from rich.table import Table

    from initrunner.cli._helpers import resolve_role_path
    from initrunner.services.operations import list_mcp_tools_sync

    role_file = resolve_role_path(role_file)

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
        list[Path],
        typer.Argument(help="Agent directories or role YAML files to expose as MCP tools"),
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
    audit_db: AuditDbOption = None,
    no_audit: NoAuditOption = False,
    skill_dir: SkillDirOption = None,
) -> None:
    """Expose InitRunner agents as an MCP server."""
    from initrunner.cli._helpers import create_audit_logger, resolve_role_paths, resolve_skill_dirs
    from initrunner.mcp.gateway import build_mcp_gateway, run_mcp_gateway

    # All output goes to stderr to keep stdout clean for stdio transport
    err_console = Console(stderr=True)

    # Validate transport
    if transport not in _VALID_TRANSPORTS:
        err_console.print(f"[red]Error:[/red] Unknown transport: {transport!r}")
        err_console.print(f"Expected one of: {', '.join(sorted(_VALID_TRANSPORTS))}")
        raise typer.Exit(1)

    # Resolve directories to role files
    role_files = resolve_role_paths(role_files)

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


@app.command("toolkit")
def mcp_toolkit(
    tools: Annotated[
        str | None,
        typer.Option(
            "--tools",
            "-T",
            help="Comma-separated tools to expose (e.g. search,csv_analysis,sql)",
        ),
    ] = None,
    config: Annotated[
        Path | None,
        typer.Option("--config", "-c", help="Path to toolkit.yaml config file"),
    ] = None,
    transport: Annotated[
        str, typer.Option("--transport", "-t", help="Transport: stdio, sse, streamable-http")
    ] = "stdio",
    host: Annotated[str, typer.Option(help="Host to bind to (sse/http)")] = "127.0.0.1",
    port: Annotated[int, typer.Option(help="Port to listen on (sse/http)")] = 8080,
    server_name: Annotated[
        str | None, typer.Option(help="MCP server name (overrides config)")
    ] = None,
) -> None:
    """Expose InitRunner tools directly as an MCP server (no agent/LLM required)."""
    from initrunner.mcp.gateway import run_mcp_gateway
    from initrunner.mcp.toolkit import (
        ToolkitConfig,
        build_toolkit,
        load_toolkit_config,
    )

    err_console = Console(stderr=True)

    if transport not in _VALID_TRANSPORTS:
        err_console.print(f"[red]Error:[/red] Unknown transport: {transport!r}")
        err_console.print(f"Expected one of: {', '.join(sorted(_VALID_TRANSPORTS))}")
        raise typer.Exit(1)

    # Load config
    tk_config: ToolkitConfig | None = None
    if config is not None:
        if not config.exists():
            err_console.print(f"[red]Error:[/red] Config file not found: {config}")
            raise typer.Exit(1)
        try:
            tk_config = load_toolkit_config(config)
        except Exception as e:
            err_console.print(f"[red]Error:[/red] Failed to load config: {e}")
            raise typer.Exit(1) from None

    if tk_config is None:
        tk_config = ToolkitConfig()

    # Override server name if specified on CLI
    if server_name is not None:
        tk_config.server_name = server_name

    # Parse --tools flag
    tool_names: list[str] | None = None
    if tools is not None:
        tool_names = [t.strip() for t in tools.split(",") if t.strip()]

    try:
        mcp = build_toolkit(tk_config, tool_names=tool_names)
    except Exception as e:
        err_console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1) from None

    err_console.print(f"[bold]MCP Toolkit:[/bold] {tk_config.server_name}")
    err_console.print(f"  Transport: {transport}")
    if tool_names:
        err_console.print(f"  Tools: {', '.join(tool_names)}")
    elif tk_config.tools:
        err_console.print(f"  Tools: {', '.join(tk_config.tools.keys())}")
    else:
        err_console.print("  Tools: search, web_reader, csv_analysis, datetime (defaults)")
    if transport != "stdio":
        err_console.print(f"  Endpoint: {host}:{port}")

    try:
        run_mcp_gateway(mcp, transport=transport, host=host, port=port)
    except Exception as e:
        err_console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1) from None
