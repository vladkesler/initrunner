"""Always-on service commands: list, info, start, status, stop, run, logs."""

from __future__ import annotations

from typing import Annotated, Any

import typer
from rich.table import Table

from initrunner.cli._helpers import console

app = typer.Typer(help="Start and operate curated always-on agent services.")


def _parse_set_pairs(pairs: list[str] | None) -> dict[str, Any]:
    """Parse ``key=value`` pairs; reject duplicates and malformed entries."""
    out: dict[str, Any] = {}
    for raw in pairs or []:
        if "=" not in raw:
            console.print(f"[red]Error:[/red] Expected key=value, got '{raw}'")
            raise typer.Exit(1)
        key, _, value = raw.partition("=")
        key = key.strip()
        if not key:
            console.print(f"[red]Error:[/red] Empty key in '{raw}'")
            raise typer.Exit(1)
        if key in out:
            console.print(f"[red]Error:[/red] Duplicate --set key '{key}'")
            raise typer.Exit(1)
        out[key] = value
    return out


@app.command("list")
def service_list() -> None:
    """List shipped services and local status."""
    from initrunner.services.always_on import list_services

    items = list_services()
    if not items:
        console.print("[dim]No services found in the catalog.[/dim]")
        return

    table = Table(title="Services")
    table.add_column("Name", style="cyan")
    table.add_column("Status")
    table.add_column("Source")
    table.add_column("Description")
    for item in items:
        status_style = {
            "running": "green",
            "stopped": "dim",
        }.get(item.status.value, "")
        status_label = f"[{status_style}]{item.status.value}[/{status_style}]"
        table.add_row(
            item.slug,
            status_label,
            item.source,
            item.description or "—",
        )
    console.print(table)


@app.command("info")
def service_info(
    slug: Annotated[str, typer.Argument(help="Service name")],
) -> None:
    """Show service metadata, params, and requirements."""
    from initrunner.services.always_on import ServiceError, info_dict

    try:
        info = info_dict(slug)
    except ServiceError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1) from None

    console.print(f"[bold]{info['slug']}[/bold]  v{info['version'] or '?'}")
    if info["description"]:
        console.print(info["description"])
    console.print(f"\n[dim]Source:[/dim] {info['source']}  [dim]Path:[/dim] {info['path']}")
    console.print(f"[dim]Status:[/dim] {info['status']}")
    console.print(f"[dim]Runtime agent name:[/dim] {info['runtime_agent_name']}")
    if info.get("primary_param"):
        console.print(f"[dim]Primary param:[/dim] {info['primary_param']}")
    console.print(f"[dim]Default every:[/dim] {info['every']}")

    if info["params"]:
        console.print("\n[bold]Parameters[/bold]")
        for name, p in info["params"].items():
            req = "required" if p["required"] else "optional"
            default = f", default={p['default']!r}" if p["default"] is not None else ""
            vals = f", values={p['values']}" if p["values"] else ""
            console.print(f"  [cyan]{name}[/cyan] ({p['type']}, {req}{default}{vals})")
            if p["description"]:
                console.print(f"    {p['description']}")

    req = info["requires"]
    if req["env"] or req["extras"]:
        console.print("\n[bold]Requires[/bold]")
        if req["env"]:
            console.print(f"  env: {', '.join(req['env'])}")
        if req["extras"]:
            console.print(f"  extras: {', '.join(req['extras'])}")
            # Escape [ ] so Rich does not treat extras as markup tags.
            extras = ",".join(req["extras"])
            console.print(f'  [dim]Install:[/dim] pip install "initrunner\\[{extras}]"')

    defaults = info["defaults"]
    console.print(
        f"\n[dim]timezone:[/dim] {defaults['timezone']}  "
        f"[dim]autonomy:[/dim] {defaults['autonomy']}"
    )


@app.command("start")
def service_start(
    slug: Annotated[str, typer.Argument(help="Service name")],
    primary: Annotated[
        str | None,
        typer.Argument(help="Value for the service primary parameter (if any)"),
    ] = None,
    set_param: Annotated[
        list[str] | None,
        typer.Option("--set", help="Parameter as key=value (repeatable)"),
    ] = None,
    every: Annotated[
        str | None,
        typer.Option("--every", help="Schedule: hourly, daily, weekly, or 5-field cron"),
    ] = None,
    sink: Annotated[
        list[str] | None,
        typer.Option("--sink", help="Sink: file:/path or webhook:url (repeatable)"),
    ] = None,
) -> None:
    """Start a service: materialize config and start its daemon."""
    from initrunner.services.always_on import ServiceError, get_catalog_entry, start_service

    try:
        entry = get_catalog_entry(slug)
    except ServiceError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1) from None

    params = _parse_set_pairs(set_param)
    primary_name = entry.definition.spec.primary_param
    if primary is not None:
        if not primary_name:
            console.print(
                f"[red]Error:[/red] Service '{slug}' has no primary parameter; use --set key=value."
            )
            raise typer.Exit(1)
        if primary_name in params:
            console.print(
                f"[red]Error:[/red] Pass primary '{primary_name}' either as a "
                f"positional argument or via --set, not both."
            )
            raise typer.Exit(1)
        params[primary_name] = primary

    try:
        result = start_service(
            slug,
            params=params or None,
            sinks=list(sink) if sink is not None else None,
            every=every,
        )
    except ServiceError as e:
        console.print("[red]Error:[/red]")
        console.print(str(e), markup=False)
        raise typer.Exit(1) from None

    state = result.state
    if result.idempotent:
        console.print(f"[green]Already running[/green] {slug}")
    else:
        console.print(f"[green]Started[/green] {slug} ({state.status.value})")
    if result.version_from and result.version_to and result.version_from != result.version_to:
        console.print(f"  [dim]catalog version:[/dim] {result.version_from} → {result.version_to}")
    if state.params:
        console.print(f"  params: {state.params}")
    console.print(f"  every: {state.every} ({state.resolved_cron} {state.timezone})")
    if state.process:
        console.print(f"  daemon pid: {state.process.pid}")
    for path in state.output_paths:
        console.print(f"  output: {path}")
    console.print(
        f"[dim]Status:[/dim] initrunner service status {slug}\n"
        f"[dim]One-shot tick:[/dim] initrunner service run {slug}"
    )


@app.command("status")
def service_status(
    slug: Annotated[str, typer.Argument(help="Service name")],
) -> None:
    """Show start state, health, and recent activity."""
    from initrunner.services.always_on import ProcessObservation, ServiceError, status

    try:
        view = status(slug)
    except ServiceError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1) from None

    s = view.state
    console.print(f"[bold]{s.slug}[/bold]  status=[cyan]{s.status.value}[/cyan]")
    if view.unverifiable_message:
        console.print(f"  [yellow]warning:[/yellow] {view.unverifiable_message}")
    if s.process and view.observation is ProcessObservation.VERIFIED_RUNNING:
        rss = f"  rss={view.rss_mb} MB" if view.rss_mb is not None else ""
        console.print(f"  daemon: running  pid={s.process.pid}{rss}")
    elif s.status.value == "running":
        console.print(f"  daemon: {view.observation.value}")
    else:
        console.print("  daemon: stopped")
    console.print(f"  every: {s.every} ({s.resolved_cron} {s.timezone})")
    if s.params:
        console.print(f"  params: {s.params}")
    for path in s.output_paths:
        console.print(f"  output: {path}")
    if view.role_path:
        console.print(f"  instance: {view.role_path}")
    if view.last_run_at:
        ok = "ok" if view.last_run_ok else "error"
        console.print(f"  last run: {view.last_run_at}  {ok}")
    else:
        console.print("  last run: (never)")
    if view.cost_today_usd is not None:
        console.print(f"  cost today: ${view.cost_today_usd:.4f}")
    if s.last_error:
        console.print(f"  [yellow]last_error:[/yellow] {s.last_error}")
    if view.log_tail and view.log_tail != "(no log yet)":
        console.print("\n[dim]Log tail:[/dim]")
        console.print(view.log_tail)


@app.command("stop")
def service_stop(
    slug: Annotated[str, typer.Argument(help="Service name")],
    purge: Annotated[
        bool,
        typer.Option(
            "--purge",
            help=(
                "Delete instance config, logs, and file outputs under "
                "~/.initrunner/services/<slug>. Does not delete audit history, "
                "memory stores, or budget state."
            ),
        ),
    ] = False,
) -> None:
    """Stop a service daemon; optionally purge local instance data."""
    from initrunner.services.always_on import ServiceError, stop_service

    try:
        stop_service(slug, purge=purge)
    except ServiceError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1) from None
    if purge:
        console.print(f"[green]Stopped and purged[/green] {slug}")
    else:
        console.print(f"[green]Stopped[/green] {slug} (instance retained)")


@app.command("logs")
def service_logs_cmd(
    slug: Annotated[str, typer.Argument(help="Service name")],
    lines: Annotated[int, typer.Option("--lines", "-n", help="Lines to show")] = 50,
) -> None:
    """Show recent daemon log lines for a service."""
    from initrunner.services.always_on import ServiceError, service_logs

    try:
        text = service_logs(slug, lines=lines)
    except ServiceError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1) from None
    console.print(text)


@app.command("run")
def service_run(
    slug: Annotated[str, typer.Argument(help="Service name")],
    model: Annotated[
        str | None,
        typer.Option("--model", help="Model override (provider:name)"),
    ] = None,
) -> None:
    """Force one service tick now (stops the daemon briefly if it was running)."""
    from initrunner.services.always_on import ServiceError, forced_run

    try:
        result = forced_run(slug, model=model)
    except ServiceError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1) from None

    if result.was_running:
        console.print(f"[dim]Stopped daemon for one-shot tick on {slug}…[/dim]")
    else:
        console.print(f"[dim]Running one-shot tick for {slug}…[/dim]")
    for msg in result.messages:
        console.print(f"[yellow]{msg}[/yellow]", markup=False)
    if result.exit_code != 0:
        raise typer.Exit(result.exit_code)
    console.print(f"[green]Tick complete[/green] for {slug}")
