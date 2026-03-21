"""Server commands: ui, tui. Pipeline display helpers."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Annotated

import typer
from rich.table import Table

from initrunner.cli._helpers import (
    console,
    create_audit_logger,
)
from initrunner.cli._options import AuditDbOption, NoAuditOption

_LOCALHOST_HOSTS = {"127.0.0.1", "localhost", "::1"}

_DOCKER = Path("/.dockerenv").exists()
_DEFAULT_UI_HOST = "0.0.0.0" if _DOCKER else "127.0.0.1"


def _display_pipeline_dry_run(pipe: object, variables: dict[str, str]) -> None:
    from initrunner.pipeline.schema import PipelineDefinition

    p: PipelineDefinition = pipe  # type: ignore[assignment]

    table = Table(title=f"Pipeline: {p.metadata.name}")
    table.add_column("Step", style="cyan")
    table.add_column("Mode")
    table.add_column("Source")
    table.add_column("Depends On")
    table.add_column("Condition")
    table.add_column("Output")

    for step in p.spec.steps:
        source = step.role_file or step.url or ""
        deps = ", ".join(step.depends_on) if step.depends_on else "(none)"
        cond = step.condition or "(always)"
        table.add_row(step.name, step.mode, source, deps, cond, step.output_format)

    console.print(table)

    if variables:
        console.print("\n[bold]Variables:[/bold]")
        for k, v in variables.items():
            console.print(f"  {k} = {v}")

    console.print(f"\n[bold]Strategy:[/bold] {p.spec.error_strategy}")
    console.print(f"[bold]Max parallel:[/bold] {p.spec.max_parallel}")
    console.print("\n[green]Pipeline definition is valid.[/green]")


def _display_pipeline_result(result: object) -> None:
    from initrunner.pipeline.executor import PipelineResult

    r: PipelineResult = result  # type: ignore[assignment]

    table = Table(title=f"Pipeline: {r.pipeline_name} ({r.pipeline_id})")
    table.add_column("Step", style="cyan")
    table.add_column("Status")
    table.add_column("Duration")
    table.add_column("Output (preview)")

    for sr in r.step_results:
        if sr.skipped:
            status = f"[dim]SKIP[/dim] ({sr.skip_reason})"
        elif sr.success:
            status = "[green]PASS[/green]"
        else:
            status = f"[red]FAIL[/red] ({sr.error})"

        duration = f"{sr.duration_ms}ms"
        preview = (sr.output[:80] + "...") if len(sr.output) > 80 else sr.output
        table.add_row(sr.name, status, duration, preview)

    console.print(table)
    total = f"[bold]Total: {r.duration_ms}ms[/bold]"
    if r.success:
        console.print(f"\n{total} [green]Pipeline succeeded[/green]")
    else:
        console.print(f"\n{total} [red]Pipeline failed[/red]")


def _resolve_dashboard_key(explicit_key: str | None, no_auth: bool, host: str) -> str | None:
    """Resolve the dashboard API key with safety checks.

    Resolution order:
    1. Explicit --api-key flag
    2. INITRUNNER_DASHBOARD_API_KEY env var
    3. Persisted key from ~/.initrunner/dashboard.key
    4. Auto-generate + persist

    Binding to non-localhost requires explicit key or --no-auth.
    """
    import os
    import secrets

    is_localhost = host in _LOCALHOST_HOSTS

    if no_auth:
        if not is_localhost:
            console.print(
                "[bold red]WARNING:[/bold red] Running without authentication on a "
                f"non-localhost address ({host}). The dashboard will be accessible to "
                "anyone who can reach this address. Agents can execute arbitrary prompts."
            )
        return None

    # 1. Explicit flag
    if explicit_key:
        return explicit_key

    # 2. Environment variable
    env_key = os.environ.get("INITRUNNER_DASHBOARD_API_KEY")
    if env_key:
        return env_key

    # Non-localhost requires explicit key (auto-generated keys printed to console
    # are unsafe when logs may be visible to others on the network)
    if not is_localhost and not _DOCKER:
        console.print(
            "[bold red]Error:[/bold red] Binding to non-localhost address "
            f"({host}) requires an explicit API key.\n"
            "Use [bold]--api-key <key>[/bold] or set "
            "[bold]INITRUNNER_DASHBOARD_API_KEY[/bold] env var.\n"
            "To disable auth entirely (NOT recommended): [bold]--no-auth[/bold]"
        )
        raise typer.Exit(1)

    # 3. Persisted key
    key_path = Path.home() / ".initrunner" / "dashboard.key"
    if key_path.exists():
        stored = key_path.read_text().strip()
        if stored:
            return stored

    # 4. Auto-generate + persist
    new_key = secrets.token_urlsafe(32)
    key_path.parent.mkdir(parents=True, exist_ok=True)

    fd = os.open(str(key_path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, new_key.encode())
    finally:
        os.close(fd)

    return new_key


def ui(
    role_dir: Annotated[Path | None, typer.Option(help="Directory to scan for roles")] = None,
    host: Annotated[str, typer.Option(help="Host to bind to")] = _DEFAULT_UI_HOST,
    port: Annotated[int, typer.Option(help="Port to listen on")] = 8420,
    no_browser: Annotated[bool, typer.Option(help="Don't open browser automatically")] = False,
    api_key: Annotated[str | None, typer.Option(help="API key for dashboard auth")] = None,
    no_auth: Annotated[bool, typer.Option(help="Disable authentication (NOT recommended)")] = False,
    audit_db: AuditDbOption = None,
    no_audit: NoAuditOption = False,
) -> None:
    """Launch the web dashboard."""
    try:
        from initrunner.api.app import run_dashboard
    except ImportError:
        console.print("[yellow]Dashboard dependencies are not installed.[/yellow]")
        if sys.stdin.isatty() and typer.confirm("Install them now?", default=True):
            from initrunner.cli._helpers import install_extra

            if install_extra("dashboard"):
                importlib.invalidate_caches()
                from initrunner.api.app import run_dashboard
            else:
                raise typer.Exit(1) from None
        else:
            console.print("Install manually: [bold]pip install 'initrunner[dashboard]'[/bold]")
            raise typer.Exit(1) from None

    from initrunner.services.discovery import get_default_role_dirs

    explicit = role_dir.resolve() if role_dir else None
    role_dirs = [d.resolve() for d in get_default_role_dirs(explicit)]

    resolved_key = _resolve_dashboard_key(api_key, no_auth, host)

    audit_logger = create_audit_logger(audit_db, no_audit)

    import atexit

    if audit_logger is not None:
        atexit.register(audit_logger.close)

    console.print(f"Starting dashboard at [cyan]http://{host}:{port}[/cyan]")
    console.print(f"API docs at [cyan]http://{host}:{port}/api/docs[/cyan]")
    if resolved_key:
        console.print(f"API key: [yellow]{resolved_key}[/yellow]")
        console.print("[dim]The browser will open with the key in the URL.[/dim]")
    else:
        console.print("[yellow]Authentication disabled.[/yellow]")

    run_dashboard(
        host=host,
        port=port,
        open_browser=not no_browser,
        api_key=resolved_key,
        role_dirs=role_dirs,
        audit_logger=audit_logger,
    )


def tui(
    role_dir: Annotated[Path | None, typer.Option(help="Directory to scan for roles")] = None,
) -> None:
    """Launch the Textual TUI dashboard."""
    try:
        import textual  # noqa: F401
    except ImportError:
        console.print("[yellow]The TUI requires the 'textual' package.[/yellow]")
        if sys.stdin.isatty() and typer.confirm("Install it now?", default=True):
            from initrunner.cli._helpers import install_extra

            if install_extra("tui"):
                importlib.invalidate_caches()
            else:
                raise typer.Exit(1) from None
        else:
            console.print("Install manually: [bold]pip install 'initrunner[tui]'[/bold]")
            raise typer.Exit(1) from None

    from initrunner.tui import run_tui

    run_tui(role_dir=role_dir)
