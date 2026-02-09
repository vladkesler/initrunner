"""Compose commands: validate, up, events, and systemd lifecycle management."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Annotated

import typer
from rich.table import Table

from initrunner.cli._helpers import console, create_audit_logger

app = typer.Typer(help="Multi-agent compose orchestration.")


@app.command("validate")
def compose_validate(
    compose_file: Annotated[Path, typer.Argument(help="Path to compose YAML")],
) -> None:
    """Validate a compose definition file."""
    from initrunner.compose.loader import ComposeLoadError, load_compose

    try:
        compose = load_compose(compose_file)
    except ComposeLoadError as e:
        console.print(f"[red]Invalid:[/red] {e}")
        raise typer.Exit(1) from None

    table = Table(title=f"Compose: {compose.metadata.name}")
    table.add_column("Service", style="cyan")
    table.add_column("Role")
    table.add_column("Sink")
    table.add_column("Depends On")
    table.add_column("Restart")

    for name, svc in compose.spec.services.items():
        sink_str = svc.sink.summary() if svc.sink else "(none)"
        deps_str = ", ".join(svc.depends_on) if svc.depends_on else "(none)"
        restart_str = svc.restart.condition
        table.add_row(name, svc.role, sink_str, deps_str, restart_str)

    console.print(table)

    # Validate role file references
    base_dir = compose_file.parent
    all_valid = True
    for name, svc in compose.spec.services.items():
        role_path = base_dir / svc.role
        if not role_path.exists():
            console.print(f"[red]Error:[/red] Role file not found for '{name}': {role_path}")
            all_valid = False

    if all_valid:
        console.print("[green]Valid[/green]")
    else:
        raise typer.Exit(1)


@app.command("up")
def compose_up(
    compose_file: Annotated[Path, typer.Argument(help="Path to compose YAML")],
    audit_db: Annotated[Path | None, typer.Option(help="Path to audit database")] = None,
    no_audit: Annotated[bool, typer.Option(help="Disable audit logging")] = False,
) -> None:
    """Start a compose orchestration (foreground)."""
    from initrunner.compose.loader import ComposeLoadError, load_compose
    from initrunner.compose.orchestrator import run_compose

    try:
        compose = load_compose(compose_file)
    except ComposeLoadError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1) from None

    audit_logger = create_audit_logger(audit_db, no_audit)

    try:
        run_compose(compose, compose_file.parent, audit_logger=audit_logger)
    finally:
        if audit_logger is not None:
            audit_logger.close()


@app.command("events")
def compose_events(
    source: Annotated[str | None, typer.Option("--source", help="Filter by source service")] = None,
    target: Annotated[str | None, typer.Option("--target", help="Filter by target service")] = None,
    status: Annotated[str | None, typer.Option("--status", help="Filter by status")] = None,
    run_id: Annotated[str | None, typer.Option("--run-id", help="Filter by source run ID")] = None,
    since: Annotated[str | None, typer.Option("--since", help="Start timestamp (ISO)")] = None,
    until: Annotated[str | None, typer.Option("--until", help="End timestamp (ISO)")] = None,
    limit: Annotated[int, typer.Option("--limit", help="Max events to show")] = 100,
    audit_db: Annotated[
        Path | None, typer.Option("--audit-db", help="Path to audit database")
    ] = None,
) -> None:
    """Query delegate routing events from the audit trail."""
    from initrunner.audit.logger import DEFAULT_DB_PATH, AuditLogger

    db_path = audit_db or DEFAULT_DB_PATH
    if not db_path.exists():
        console.print(f"[red]Error:[/red] Audit database not found: {db_path}")
        raise typer.Exit(1)

    with AuditLogger(db_path) as logger:
        events = logger.query_delegate_events(
            source_service=source,
            target_service=target,
            status=status,
            source_run_id=run_id,
            since=since,
            until=until,
            limit=limit,
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
def compose_install(
    compose_file: Annotated[Path, typer.Argument(help="Path to compose YAML")],
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
            help="Generate a template .env file in the compose directory",
        ),
    ] = False,
) -> None:
    """Install a systemd user unit for a compose project.

    The service runs in a restricted systemd environment. Environment
    variables from your shell (e.g., exports in .bashrc) are NOT visible.
    Use --env-file or place a .env file in the compose directory.
    """
    from initrunner.compose.loader import ComposeLoadError, load_compose
    from initrunner.compose.systemd import (
        SystemdError,
        check_linger_enabled,
        generate_env_template,
        install_unit,
    )

    try:
        compose = load_compose(compose_file)
    except ComposeLoadError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1) from None

    try:
        info = install_unit(
            compose.metadata.name,
            compose_file,
            force=force,
            env_file=env_file,
        )
    except SystemdError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1) from None

    console.print(f"[green]Installed[/green] {info.unit_name}")
    console.print(f"  Unit file: {info.unit_path}")

    console.print("\n[dim]Next steps:[/dim]")
    console.print(f"  Start now:      initrunner compose start {compose.metadata.name}")
    console.print(f"  Enable on boot: systemctl --user enable {info.unit_name}")
    console.print(f"  View status:    initrunner compose status {compose.metadata.name}")
    console.print(f"  View logs:      initrunner compose logs {compose.metadata.name}")

    if not check_linger_enabled():
        console.print(
            "\n[yellow]Warning:[/yellow] User lingering is not enabled. "
            "This service will stop when you log out.\n"
            "  To fix: [bold]loginctl enable-linger $USER[/bold]"
        )

    env_path = compose_file.parent / ".env"
    if not env_path.exists() and env_file is None:
        console.print(
            "\n[dim]Hint:[/dim] No .env file found. Shell env vars are NOT inherited "
            "by systemd services.\n"
            "  Use --generate-env to create a template, or --env-file to specify one."
        )

    if generate_env:
        env_path = compose_file.parent / ".env"
        if env_path.exists():
            console.print(f"[yellow]Skipped:[/yellow] {env_path} already exists.")
        else:
            env_path.write_text(generate_env_template(compose.metadata.name))
            console.print(f"[green]Created[/green] {env_path}")


@app.command("uninstall")
def compose_uninstall(
    name_or_file: Annotated[str, typer.Argument(help="Compose name or path to compose YAML")],
) -> None:
    """Uninstall a systemd user unit for a compose project."""
    from initrunner.compose.systemd import SystemdError, resolve_compose_name, uninstall_unit

    try:
        compose_name = resolve_compose_name(name_or_file)
    except (FileNotFoundError, Exception) as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1) from None

    try:
        path = uninstall_unit(compose_name)
    except SystemdError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1) from None

    console.print(f"[green]Uninstalled[/green] {path.name}")


def _systemctl_wrapper(action: str, name_or_file: str) -> None:
    """Shared helper for start/stop/restart commands."""
    from initrunner.compose.systemd import (
        SystemdError,
        check_systemd_available,
        resolve_compose_name,
        sanitize_unit_name,
    )

    try:
        check_systemd_available()
        compose_name = resolve_compose_name(name_or_file)
    except (FileNotFoundError, SystemdError) as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1) from None

    sanitized = sanitize_unit_name(compose_name)
    unit_name = f"initrunner-{sanitized}.service"

    try:
        subprocess.run(
            ["systemctl", "--user", action, unit_name],
            check=True,
            timeout=30,
        )
    except subprocess.CalledProcessError as e:
        console.print(f"[red]Error:[/red] systemctl {action} failed (exit {e.returncode}).")
        raise typer.Exit(1) from None
    except subprocess.TimeoutExpired:
        console.print(f"[red]Error:[/red] systemctl {action} timed out.")
        raise typer.Exit(1) from None

    console.print(f"[green]{action.capitalize()}ed[/green] {unit_name}")


@app.command("start")
def compose_start(
    name_or_file: Annotated[str, typer.Argument(help="Compose name or path to compose YAML")],
) -> None:
    """Start a compose systemd service."""
    _systemctl_wrapper("start", name_or_file)


@app.command("stop")
def compose_stop(
    name_or_file: Annotated[str, typer.Argument(help="Compose name or path to compose YAML")],
) -> None:
    """Stop a compose systemd service."""
    _systemctl_wrapper("stop", name_or_file)


@app.command("restart")
def compose_restart(
    name_or_file: Annotated[str, typer.Argument(help="Compose name or path to compose YAML")],
) -> None:
    """Restart a compose systemd service."""
    _systemctl_wrapper("restart", name_or_file)


@app.command("status")
def compose_status(
    name_or_file: Annotated[str, typer.Argument(help="Compose name or path to compose YAML")],
) -> None:
    """Show the systemd status for a compose service."""
    from initrunner.compose.systemd import (
        SystemdError,
        get_unit_status,
        resolve_compose_name,
    )

    try:
        compose_name = resolve_compose_name(name_or_file)
    except (FileNotFoundError, Exception) as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1) from None

    try:
        output = get_unit_status(compose_name)
    except SystemdError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1) from None

    console.print(output)


@app.command("logs")
def compose_logs(
    name_or_file: Annotated[str, typer.Argument(help="Compose name or path to compose YAML")],
    follow: Annotated[bool, typer.Option("--follow", "-f", help="Follow log output")] = False,
    lines: Annotated[int, typer.Option("--lines", "-n", help="Number of lines to show")] = 50,
) -> None:
    """Show journald logs for a compose service."""
    from initrunner.compose.systemd import (
        SystemdError,
        check_systemd_available,
        resolve_compose_name,
        sanitize_unit_name,
    )

    try:
        check_systemd_available()
        compose_name = resolve_compose_name(name_or_file)
    except (FileNotFoundError, SystemdError) as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1) from None

    sanitized = sanitize_unit_name(compose_name)
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
