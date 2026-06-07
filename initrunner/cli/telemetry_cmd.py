"""Telemetry status and opt-out commands."""

from __future__ import annotations

import typer

from initrunner.cli._helpers import console

app = typer.Typer(help="Manage anonymous usage telemetry.")


@app.command("status")
def telemetry_status() -> None:
    """Show telemetry status and what is collected."""
    from initrunner import telemetry

    info = telemetry.status()
    if info["enabled"]:
        console.print("Usage telemetry: [green]enabled[/green]")
    else:
        console.print(f"Usage telemetry: [yellow]disabled[/yellow] (reason: {info['reason']})")
    console.print(f"Install ID: {info['install_id'] or '[dim](not yet generated)[/dim]'}")
    console.print(f"Config: {info['path']}")
    console.print()
    console.print(
        "[dim]Collected: command name, status, error class, duration bucket, OS, "
        "Python version, InitRunner version.[/dim]"
    )
    console.print(
        "[dim]Never collected: prompts, file contents, paths, arguments, or API keys.[/dim]"
    )
    console.print("[dim]Opt out: initrunner telemetry disable  (or set DO_NOT_TRACK=1)[/dim]")


@app.command("enable")
def telemetry_enable() -> None:
    """Enable anonymous usage telemetry."""
    from initrunner import telemetry

    telemetry.enable()
    console.print("[green]Telemetry enabled.[/green]")


@app.command("disable")
def telemetry_disable() -> None:
    """Disable anonymous usage telemetry."""
    from initrunner import telemetry

    telemetry.disable()
    console.print("Telemetry disabled. No usage data will be sent.")


@app.command("reset")
def telemetry_reset() -> None:
    """Rotate the anonymous install ID."""
    from initrunner import telemetry

    new_id = telemetry.reset()
    console.print(f"Install ID rotated: {new_id}")
