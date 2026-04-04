"""Flow commands: validate, up, events, and systemd lifecycle management."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Annotated

import typer
from rich.table import Table

from initrunner.cli._helpers import console, create_audit_logger
from initrunner.cli._options import AuditDbOption, NoAuditOption

app = typer.Typer(help="Multi-agent flow orchestration.")


@app.command("new")
def flow_new(
    name: Annotated[str, typer.Argument(help="Project name (becomes directory name)")],
    pattern: Annotated[str, typer.Option("--pattern", help="Flow pattern")] = "chain",
    agents: Annotated[int, typer.Option("--agents", help="Number of agents")] = 3,
    shared_memory: Annotated[
        bool, typer.Option("--shared-memory", help="Enable shared memory store")
    ] = False,
    provider: Annotated[str | None, typer.Option(help="Model provider")] = None,
    model: Annotated[str | None, typer.Option(help="Model name")] = None,
    output: Annotated[Path, typer.Option(help="Parent directory for the project")] = Path("."),
    force: Annotated[
        bool, typer.Option("--force", "-f", help="Overwrite existing directory")
    ] = False,
    list_patterns: Annotated[
        bool, typer.Option("--list-patterns", help="Show available patterns and exit")
    ] = False,
) -> None:
    """Scaffold a new flow project directory."""
    from initrunner.templates import COMPOSE_PATTERNS

    if list_patterns:
        table = Table(title="Flow Patterns")
        table.add_column("Name", style="cyan")
        table.add_column("Description")
        for pname, desc in COMPOSE_PATTERNS.items():
            table.add_row(pname, desc)
        console.print(table)
        raise typer.Exit(0)

    from initrunner.agent.loader import _load_dotenv
    from initrunner.services.flow import scaffold_flow_project
    from initrunner.services.roles import _detect_provider

    _load_dotenv(Path.cwd())

    resolved_provider = provider or _detect_provider()

    try:
        result = scaffold_flow_project(
            name,
            pattern=pattern,
            agents=agents,
            shared_memory=shared_memory,
            provider=resolved_provider,
            model_name=model,
            output_dir=output,
            force=force,
        )
    except (ValueError, FileExistsError) as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1) from None

    console.print(f"[green]Created[/green] {result.project_dir}/")
    console.print(f"  {result.flow_path.name}")
    for rp in result.role_paths:
        console.print(f"  roles/{rp.name}")

    console.print("\n[dim]Next steps:[/dim]")
    console.print(f"  cd {result.project_dir}")
    console.print("  initrunner flow validate flow.yaml")
    console.print("  initrunner flow up flow.yaml")


@app.command("validate")
def flow_validate(
    flow_file: Annotated[Path, typer.Argument(help="Path to flow YAML")],
) -> None:
    """Validate a flow definition file."""
    from initrunner.flow.loader import FlowLoadError
    from initrunner.services.flow import load_flow_sync

    try:
        flow = load_flow_sync(flow_file)
    except FlowLoadError as e:
        console.print(f"[red]Invalid:[/red] {e}")
        console.print(
            "[dim]Hint:[/dim] Run [bold]initrunner validate[/bold] on each agent role individually."
        )
        raise typer.Exit(1) from None

    table = Table(title=f"Flow: {flow.metadata.name}")
    table.add_column("Agent", style="cyan")
    table.add_column("Role")
    table.add_column("Sink")
    table.add_column("Needs")
    table.add_column("Restart")

    for name, agent in flow.spec.agents.items():
        sink_str = agent.sink.summary() if agent.sink else "(none)"
        needs_str = ", ".join(agent.needs) if agent.needs else "(none)"
        restart_str = agent.restart.condition
        table.add_row(name, agent.role, sink_str, needs_str, restart_str)

    console.print(table)

    # Validate role file references
    base_dir = flow_file.parent
    all_valid = True
    for name, agent in flow.spec.agents.items():
        role_path = base_dir / agent.role
        if not role_path.exists():
            console.print(f"[red]Error:[/red] Role file not found for '{name}': {role_path}")
            console.print(
                "[dim]Hint:[/dim] Check that role paths in flow.yaml"
                " are relative to the flow file directory."
            )
            all_valid = False

    if all_valid:
        console.print("[green]Valid[/green]")
    else:
        raise typer.Exit(1)


@app.command("up")
def flow_up(
    flow_file: Annotated[Path, typer.Argument(help="Path to flow YAML")],
    audit_db: AuditDbOption = None,
    no_audit: NoAuditOption = False,
) -> None:
    """Start a flow orchestration (foreground)."""
    from initrunner.flow.loader import FlowLoadError
    from initrunner.services.flow import load_flow_sync, run_flow_sync

    try:
        flow = load_flow_sync(flow_file)
    except FlowLoadError as e:
        console.print(f"[red]Error:[/red] {e}")
        console.print(
            f"[dim]Hint:[/dim] Run [bold]initrunner flow validate {flow_file}[/bold] first."
        )
        raise typer.Exit(1) from None

    audit_logger = create_audit_logger(audit_db, no_audit)

    try:
        run_flow_sync(flow, flow_file.parent, audit_logger=audit_logger)
    finally:
        if audit_logger is not None:
            audit_logger.close()


@app.command("events")
def flow_events(
    source: Annotated[str | None, typer.Option("--source", help="Filter by source agent")] = None,
    target: Annotated[str | None, typer.Option("--target", help="Filter by target agent")] = None,
    status: Annotated[str | None, typer.Option("--status", help="Filter by status")] = None,
    run_id: Annotated[str | None, typer.Option("--run-id", help="Filter by source run ID")] = None,
    since: Annotated[str | None, typer.Option("--since", help="Start timestamp (ISO)")] = None,
    until: Annotated[str | None, typer.Option("--until", help="End timestamp (ISO)")] = None,
    limit: Annotated[int, typer.Option("--limit", help="Max events to show")] = 100,
    audit_db: AuditDbOption = None,
) -> None:
    """Query delegate routing events from the audit trail."""
    from initrunner.audit.logger import DEFAULT_DB_PATH
    from initrunner.services.operations import query_delegate_events_sync

    db_path = Path(audit_db or DEFAULT_DB_PATH)
    if not db_path.exists():
        console.print(f"[red]Error:[/red] Audit database not found: {db_path}")
        console.print(
            "[dim]Hint:[/dim] Run [bold]initrunner flow up[/bold] first to create audit data."
        )
        raise typer.Exit(1)

    events = query_delegate_events_sync(
        source_service=source,
        target_service=target,
        status=status,
        source_run_id=run_id,
        since=since,
        until=until,
        limit=limit,
        audit_db=db_path,
    )

    if not events:
        console.print("[dim]No delegate events found.[/dim]")
        return

    _STATUS_STYLES = {
        "delivered": "green",
        "dropped": "red",
        "filtered": "yellow",
        "error": "red",
    }

    table = Table(title=f"Delegate Events ({len(events)})")
    table.add_column("Timestamp", style="dim")
    table.add_column("Source", style="cyan")
    table.add_column("Target", style="cyan")
    table.add_column("Status")
    table.add_column("Run ID", style="dim")
    table.add_column("Reason")
    table.add_column("Trace", style="dim")

    for evt in events:
        style = _STATUS_STYLES.get(evt.status, "")
        status_cell = f"[{style}]{evt.status}[/{style}]" if style else evt.status
        table.add_row(
            evt.timestamp,
            evt.source_service,
            evt.target_service,
            status_cell,
            evt.source_run_id,
            evt.reason or "",
            evt.trace or "",
        )

    console.print(table)


# ---------------------------------------------------------------------------
# systemd lifecycle commands
# ---------------------------------------------------------------------------


@app.command("install")
def flow_install(
    flow_file: Annotated[Path, typer.Argument(help="Path to flow YAML")],
    force: Annotated[
        bool,
        typer.Option("--force", "-f", help="Overwrite existing unit file"),
    ] = False,
    env_file: Annotated[
        Path | None,
        typer.Option("--env-file", help="Additional EnvironmentFile for the unit"),
    ] = None,
    generate_env: Annotated[
        bool,
        typer.Option(
            "--generate-env",
            help="Generate a template .env file in the flow directory",
        ),
    ] = False,
) -> None:
    """Install a systemd user unit for a flow project.

    The service runs in a restricted systemd environment. Environment
    variables from your shell (e.g., exports in .bashrc) are NOT visible.
    Use --env-file or place a .env file in the flow directory.
    """
    from initrunner.flow.loader import FlowLoadError, load_flow
    from initrunner.flow.systemd import (
        SystemdError,
        check_linger_enabled,
        generate_env_template,
        install_unit,
    )

    try:
        flow = load_flow(flow_file)
    except FlowLoadError as e:
        console.print(f"[red]Error:[/red] {e}")
        console.print(
            f"[dim]Hint:[/dim] Run [bold]initrunner flow validate {flow_file}[/bold] first."
        )
        raise typer.Exit(1) from None

    try:
        info = install_unit(
            flow.metadata.name,
            flow_file,
            force=force,
            env_file=env_file,
        )
    except SystemdError as e:
        console.print(f"[red]Error:[/red] {e}")
        console.print(
            "[dim]Hint:[/dim] Make sure systemd user services are"
            " available: [bold]systemctl --user status[/bold]"
        )
        raise typer.Exit(1) from None

    console.print(f"[green]Installed[/green] {info.unit_name}")
    console.print(f"  Unit file: {info.unit_path}")

    console.print("\n[dim]Next steps:[/dim]")
    console.print(f"  Start now:      initrunner flow start {flow.metadata.name}")
    console.print(f"  Enable on boot: systemctl --user enable {info.unit_name}")
    console.print(f"  View status:    initrunner flow status {flow.metadata.name}")
    console.print(f"  View logs:      initrunner flow logs {flow.metadata.name}")

    if not check_linger_enabled():
        console.print(
            "\n[yellow]Warning:[/yellow] User lingering is not enabled. "
            "This service will stop when you log out.\n"
            "  To fix: [bold]loginctl enable-linger $USER[/bold]"
        )

    env_path = flow_file.parent / ".env"
    if not env_path.exists() and env_file is None:
        console.print(
            "\n[dim]Hint:[/dim] No .env file found. Shell env vars are NOT inherited "
            "by systemd services.\n"
            "  Use --generate-env to create a template, or --env-file to specify one."
        )

    if generate_env:
        env_path = flow_file.parent / ".env"
        if env_path.exists():
            console.print(f"[yellow]Skipped:[/yellow] {env_path} already exists.")
        else:
            env_path.write_text(generate_env_template(flow.metadata.name))
            console.print(f"[green]Created[/green] {env_path}")


@app.command("uninstall")
def flow_uninstall(
    name_or_file: Annotated[str, typer.Argument(help="Flow name or path to flow YAML")],
) -> None:
    """Uninstall a systemd user unit for a flow project."""
    from initrunner.flow.systemd import SystemdError, resolve_flow_name, uninstall_unit

    try:
        flow_name = resolve_flow_name(name_or_file)
    except (FileNotFoundError, Exception) as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1) from None

    try:
        path = uninstall_unit(flow_name)
    except SystemdError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1) from None

    console.print(f"[green]Uninstalled[/green] {path.name}")


def _systemctl_wrapper(action: str, name_or_file: str) -> None:
    """Shared helper for start/stop/restart commands."""
    from initrunner.flow.systemd import (
        SystemdError,
        check_systemd_available,
        resolve_flow_name,
        sanitize_unit_name,
    )

    try:
        check_systemd_available()
        flow_name = resolve_flow_name(name_or_file)
    except (FileNotFoundError, SystemdError) as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1) from None

    sanitized = sanitize_unit_name(flow_name)
    unit_name = f"initrunner-{sanitized}.service"

    try:
        subprocess.run(
            ["systemctl", "--user", action, unit_name],
            check=True,
            timeout=30,
        )
    except subprocess.CalledProcessError as e:
        console.print(f"[red]Error:[/red] systemctl {action} failed (exit {e.returncode}).")
        console.print("[dim]Hint:[/dim] Check logs with [bold]initrunner flow logs[/bold].")
        raise typer.Exit(1) from None
    except subprocess.TimeoutExpired:
        console.print(f"[red]Error:[/red] systemctl {action} timed out.")
        raise typer.Exit(1) from None

    console.print(f"[green]{action.capitalize()}ed[/green] {unit_name}")


@app.command("start")
def flow_start(
    name_or_file: Annotated[str, typer.Argument(help="Flow name or path to flow YAML")],
) -> None:
    """Start a flow systemd service."""
    _systemctl_wrapper("start", name_or_file)


@app.command("stop")
def flow_stop(
    name_or_file: Annotated[str, typer.Argument(help="Flow name or path to flow YAML")],
) -> None:
    """Stop a flow systemd service."""
    _systemctl_wrapper("stop", name_or_file)


@app.command("restart")
def flow_restart(
    name_or_file: Annotated[str, typer.Argument(help="Flow name or path to flow YAML")],
) -> None:
    """Restart a flow systemd service."""
    _systemctl_wrapper("restart", name_or_file)


@app.command("status")
def flow_status(
    name_or_file: Annotated[str, typer.Argument(help="Flow name or path to flow YAML")],
) -> None:
    """Show the systemd status for a flow service."""
    from initrunner.flow.systemd import (
        SystemdError,
        get_unit_status,
        resolve_flow_name,
    )

    try:
        flow_name = resolve_flow_name(name_or_file)
    except (FileNotFoundError, Exception) as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1) from None

    try:
        output = get_unit_status(flow_name)
    except SystemdError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1) from None

    console.print(output)


@app.command("logs")
def flow_logs(
    name_or_file: Annotated[str, typer.Argument(help="Flow name or path to flow YAML")],
    follow: Annotated[bool, typer.Option("--follow", "-f", help="Follow log output")] = False,
    lines: Annotated[int, typer.Option("--lines", "-n", help="Number of lines to show")] = 50,
) -> None:
    """Show journald logs for a flow service."""
    from initrunner.flow.systemd import (
        SystemdError,
        check_systemd_available,
        resolve_flow_name,
        sanitize_unit_name,
    )

    try:
        check_systemd_available()
        flow_name = resolve_flow_name(name_or_file)
    except (FileNotFoundError, SystemdError) as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1) from None

    sanitized = sanitize_unit_name(flow_name)
    unit_name = f"initrunner-{sanitized}.service"

    cmd = [
        "journalctl",
        "--user",
        f"--unit={unit_name}",
        f"--lines={lines}",
        "--no-pager",
    ]
    if follow:
        cmd.append("--follow")

    try:
        subprocess.run(cmd, check=False, timeout=None if follow else 30)
    except subprocess.TimeoutExpired:
        console.print("[red]Error:[/red] journalctl timed out.")
        raise typer.Exit(1) from None
    except KeyboardInterrupt:
        pass
