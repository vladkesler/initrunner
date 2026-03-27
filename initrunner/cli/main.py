"""Typer CLI for InitRunner — wiring hub for command modules."""

from __future__ import annotations

from typing import Annotated

import typer

from initrunner.cli._helpers import console
from initrunner.cli.audit_cmd import app as audit_app
from initrunner.cli.compose_cmd import app as compose_app
from initrunner.cli.examples_cmd import app as examples_app
from initrunner.cli.hub_cmd import app as hub_app
from initrunner.cli.mcp_cmd import app as mcp_app
from initrunner.cli.memory_cmd import app as memory_app
from initrunner.cli.skill_cmd import app as skill_app

app = typer.Typer(
    name="initrunner",
    help="A lightweight AI agent runner.",
    no_args_is_help=False,
)

# Sub-app and command registrations are below the callback (after lazy imports).
# See "Command registrations" block.


# ---------------------------------------------------------------------------
# Callbacks
# ---------------------------------------------------------------------------


def version_callback(value: bool) -> None:
    if value:
        from initrunner import __version__

        console.print(f"initrunner {__version__}")
        raise typer.Exit()


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    version: Annotated[
        bool | None,
        typer.Option("--version", callback=version_callback, is_eager=True),
    ] = None,
    verbose: Annotated[
        bool,
        typer.Option("--verbose", help="Enable debug logging"),
    ] = False,
) -> None:
    """InitRunner — a lightweight AI agent runner."""
    from initrunner._log import setup_logging

    setup_logging(verbose=verbose)

    if ctx.invoked_subcommand is not None:
        return

    # No subcommand — handle based on environment
    import sys

    if not sys.stdin.isatty():
        # Non-TTY (piped/scripted): show help and exit
        console.print(ctx.get_help())
        raise typer.Exit()

    from initrunner.services.setup import needs_setup

    if needs_setup():
        # TTY + no config: hint to run setup
        from rich.panel import Panel

        console.print(
            Panel(
                "No provider configured yet.\n"
                "Run [bold]initrunner setup[/bold] to get started,\n"
                "or launch [bold]initrunner dashboard[/bold] to configure in the browser.",
                title="Setup Required",
                border_style="yellow",
            )
        )
        raise typer.Exit(1)
    else:
        # TTY + configured: offer action menu
        from rich.prompt import Prompt

        from initrunner._compat import is_dashboard_available

        options: list[tuple[str, str]] = []
        if is_dashboard_available():
            options.append(("Dashboard (web UI)", "dashboard"))
        options.append(("Quick chat (REPL)", "repl"))
        options.append(("Create an agent", "new"))

        # Default: Dashboard when available, otherwise Quick chat
        default_idx = "1"

        console.print()
        for i, (label, _key) in enumerate(options, 1):
            console.print(f"  [bold]{i}[/bold]. {label}")

        try:
            choice = Prompt.ask(
                "\nWhat would you like to do?",
                choices=[str(i) for i in range(1, len(options) + 1)],
                default=default_idx,
            )
        except (KeyboardInterrupt, EOFError):
            raise typer.Exit() from None

        selected = options[int(choice) - 1][1]

        if selected == "dashboard":
            from initrunner.cli.dashboard_cmd import launch_dashboard

            launch_dashboard()
        elif selected == "repl":
            from initrunner.services.providers import detect_bot_tokens

            tokens = detect_bot_tokens()
            if tokens:
                platforms = ", ".join(tokens)
                console.print(
                    f"[dim]Hint: bot tokens detected ({platforms}). "
                    f"Use 'initrunner run --bot telegram' or '--bot discord' to launch a bot.[/dim]"
                )

            from initrunner.cli._ephemeral import dispatch_ephemeral

            dispatch_ephemeral()
        elif selected == "new":
            from initrunner.cli.new_cmd import new

            new()


# ---------------------------------------------------------------------------
# Command registrations — plain functions from *_cmd modules
# ---------------------------------------------------------------------------

from initrunner.cli.dashboard_cmd import dashboard  # noqa: E402
from initrunner.cli.desktop_cmd import desktop  # noqa: E402
from initrunner.cli.doctor_cmd import doctor  # noqa: E402
from initrunner.cli.eval_cmd import test  # noqa: E402
from initrunner.cli.ingest_cmd import ingest  # noqa: E402
from initrunner.cli.new_cmd import new  # noqa: E402
from initrunner.cli.plugin_cmd import plugins  # noqa: E402
from initrunner.cli.registry_cmd import (  # noqa: E402
    info,
    install,
    list_roles,
    login,
    logout,
    publish,
    pull,
    search,
    uninstall,
    update,
    whoami,
)
from initrunner.cli.role_cmd import configure, setup, validate  # noqa: E402
from initrunner.cli.run_cmd import run  # noqa: E402

# --- Getting Started ---
app.command(rich_help_panel="Getting Started")(run)
app.command(rich_help_panel="Getting Started")(new)
app.command(rich_help_panel="Getting Started")(setup)
app.command(rich_help_panel="Getting Started")(doctor)
app.add_typer(examples_app, name="examples", rich_help_panel="Getting Started")

# --- Run & Test ---
app.command(rich_help_panel="Run & Test")(test)
app.command(rich_help_panel="Run & Test")(ingest)
app.command(rich_help_panel="Run & Test")(validate)
app.command(rich_help_panel="Run & Test")(configure)

# --- Interfaces ---
app.command(rich_help_panel="Interfaces")(dashboard)
app.command(rich_help_panel="Interfaces")(desktop)
app.add_typer(compose_app, name="compose", rich_help_panel="Interfaces")
app.add_typer(mcp_app, name="mcp", rich_help_panel="Interfaces")

# --- Package Registry ---
app.command(rich_help_panel="Package Registry")(install)
app.command(rich_help_panel="Package Registry")(uninstall)
app.command("list", rich_help_panel="Package Registry")(list_roles)
app.command(rich_help_panel="Package Registry")(update)
app.command(rich_help_panel="Package Registry")(search)
app.command(rich_help_panel="Package Registry")(info)
app.command(rich_help_panel="Package Registry")(publish)
app.command(rich_help_panel="Package Registry")(pull)
app.command(rich_help_panel="Package Registry")(login)
app.command(rich_help_panel="Package Registry")(logout)
app.command(rich_help_panel="Package Registry")(whoami)

# --- Agent Internals ---
app.command(rich_help_panel="Agent Internals")(plugins)
app.add_typer(skill_app, name="skill", rich_help_panel="Agent Internals")
app.add_typer(memory_app, name="memory", rich_help_panel="Agent Internals")
app.add_typer(audit_app, name="audit", rich_help_panel="Agent Internals")

# --- Deprecated (hidden from help) ---
app.add_typer(hub_app, name="hub", hidden=True)


def app_entry() -> None:
    """Entry point for the CLI."""
    app()
