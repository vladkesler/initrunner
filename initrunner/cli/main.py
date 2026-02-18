"""Typer CLI for InitRunner — wiring hub for command modules."""

from __future__ import annotations

from typing import Annotated

import typer

from initrunner.cli._helpers import console
from initrunner.cli.audit_cmd import app as audit_app
from initrunner.cli.compose_cmd import app as compose_app
from initrunner.cli.examples_cmd import app as examples_app
from initrunner.cli.mcp_cmd import app as mcp_app
from initrunner.cli.memory_cmd import app as memory_app
from initrunner.cli.skill_cmd import app as skill_app

app = typer.Typer(
    name="initrunner",
    help="A lightweight AI agent runner.",
    no_args_is_help=True,
)

# Sub-app registrations
app.add_typer(audit_app, name="audit")
app.add_typer(compose_app, name="compose")
app.add_typer(examples_app, name="examples")
app.add_typer(mcp_app, name="mcp")
app.add_typer(memory_app, name="memory")
app.add_typer(skill_app, name="skill")


# ---------------------------------------------------------------------------
# Callbacks
# ---------------------------------------------------------------------------


def version_callback(value: bool) -> None:
    if value:
        from initrunner import __version__

        console.print(f"initrunner {__version__}")
        raise typer.Exit()


@app.callback()
def main(
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


# ---------------------------------------------------------------------------
# Command registrations — plain functions from *_cmd modules
# ---------------------------------------------------------------------------

from initrunner.cli.doctor_cmd import doctor  # noqa: E402
from initrunner.cli.plugin_cmd import plugins  # noqa: E402
from initrunner.cli.registry_cmd import (  # noqa: E402
    info,
    install,
    list_roles,
    search,
    uninstall,
    update,
)
from initrunner.cli.role_cmd import create, init, setup, validate  # noqa: E402
from initrunner.cli.run_cmd import daemon, ingest, run, test  # noqa: E402
from initrunner.cli.server_cmd import pipeline, serve, tui, ui  # noqa: E402

app.command()(validate)
app.command()(init)
app.command()(create)
app.command()(setup)
app.command()(run)
app.command()(test)
app.command()(ingest)
app.command()(daemon)
app.command()(serve)
app.command()(pipeline)
app.command()(ui)
app.command()(tui)
app.command()(plugins)
app.command()(install)
app.command()(uninstall)
app.command()(search)
app.command()(info)
app.command("list")(list_roles)
app.command()(update)
app.command()(doctor)


def app_entry() -> None:
    """Entry point for the CLI."""
    app()
