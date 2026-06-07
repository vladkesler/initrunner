"""Typer CLI for InitRunner — wiring hub for command modules."""

from __future__ import annotations

from typing import Annotated

import typer

from initrunner.cli._helpers import console
from initrunner.cli.a2a_cmd import app as a2a_app
from initrunner.cli.audit_cmd import app as audit_app
from initrunner.cli.examples_cmd import app as examples_app
from initrunner.cli.export_cmd import app as export_app
from initrunner.cli.flow_cmd import app as flow_app
from initrunner.cli.hub_cmd import app as hub_app
from initrunner.cli.mcp_cmd import app as mcp_app
from initrunner.cli.memory_cmd import app as memory_app
from initrunner.cli.skill_cmd import app as skill_app
from initrunner.cli.telemetry_cmd import app as telemetry_app

app = typer.Typer(
    name="initrunner",
    help="A lightweight AI agent runner.",
    no_args_is_help=False,
)

# Command name captured by the main() callback for the telemetry hook in
# app_entry(). A plain module global (the CLI is single-process) read back when
# the command finishes; eager-callback paths (--help/--version) fall back to an
# argv scan in _resolve_command().
_invoked_command: str | None = None

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

    global _invoked_command
    _invoked_command = ctx.invoked_subcommand

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
        # TTY + no config: offer an offline build, else hint to run setup.
        from rich.panel import Panel
        from rich.prompt import Confirm

        console.print(
            Panel(
                "No provider configured yet.\n"
                "Run [bold]initrunner setup[/bold] to add an API key,\n"
                "or launch [bold]initrunner dashboard[/bold] to configure in the browser.",
                title="Setup Required",
                border_style="yellow",
            )
        )
        try:
            build_offline = Confirm.ask("Build an agent now without AI (offline)?", default=False)
        except (KeyboardInterrupt, EOFError):
            raise typer.Exit(1) from None
        if build_offline:
            from initrunner.cli.new_cmd import new

            new(offline=True)
            raise typer.Exit()
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

from initrunner.cli.approvals_cmd import approve, pending  # noqa: E402
from initrunner.cli.cost_cmd import app as cost_app  # noqa: E402
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
from initrunner.cli.vault_cmd import app as vault_app  # noqa: E402

# --- Getting Started ---
app.command(rich_help_panel="Getting Started")(run)
app.command(rich_help_panel="Getting Started")(new)
app.command(rich_help_panel="Getting Started")(setup)
app.command(rich_help_panel="Getting Started")(doctor)
app.add_typer(examples_app, name="examples", rich_help_panel="Getting Started")
app.add_typer(export_app, name="export", rich_help_panel="Getting Started")

# --- Run & Test ---
app.command(rich_help_panel="Run & Test")(test)
app.command(rich_help_panel="Run & Test")(ingest)
app.command(rich_help_panel="Run & Test")(validate)
app.command(rich_help_panel="Run & Test")(configure)

# --- Interfaces ---
app.command(rich_help_panel="Interfaces")(dashboard)
app.command(rich_help_panel="Interfaces")(desktop)
app.add_typer(a2a_app, name="a2a", rich_help_panel="Interfaces")
app.add_typer(flow_app, name="flow", rich_help_panel="Interfaces")
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
app.add_typer(cost_app, name="cost", rich_help_panel="Agent Internals")
app.add_typer(vault_app, name="vault", rich_help_panel="Agent Internals")
app.command("approve", rich_help_panel="Agent Internals")(approve)
app.command("pending", rich_help_panel="Agent Internals")(pending)
app.add_typer(telemetry_app, name="telemetry", rich_help_panel="Agent Internals")

# --- Deprecated (hidden from help) ---
app.add_typer(hub_app, name="hub", hidden=True)


def _resolve_command() -> str:
    """Best-effort command name for telemetry.

    Prefers the value the main() callback captured; falls back to scanning argv
    for paths where the callback never runs (``--help``, ``--version``, parse
    errors). The value is normalized to the known-command allowlist downstream.
    """
    if _invoked_command:
        return _invoked_command
    import sys

    for arg in sys.argv[1:]:
        if arg in ("--help", "-h"):
            return "help"
        if arg == "--version":
            return "version"
        if not arg.startswith("-"):
            return arg
    return "other"


_CONSENT_SKIP_COMMANDS = {"telemetry", "help", "version"}
_CONSENT_SKIP_FLAGS = {"--help", "-h", "--install-completion", "--show-completion"}


def _maybe_prompt_telemetry_consent() -> None:
    """Ask once, on an interactive first run, before any telemetry is sent.

    Telemetry is opt-in: this is the only place consent is granted interactively.
    Best-effort and silent in every non-interactive or already-decided case, so
    pipes, daemons, scripts, ``--help``, and completion never block or prompt.
    """
    import sys

    from initrunner import telemetry

    try:
        if not telemetry.consent_needed():
            return
        if not (sys.stdin.isatty() and sys.stdout.isatty()):
            return
        # _resolve_command() returns the subcommand even for `... doctor --help`,
        # so also reject help/completion flags appearing anywhere in argv.
        if _resolve_command() in _CONSENT_SKIP_COMMANDS:
            return
        if any(arg in _CONSENT_SKIP_FLAGS for arg in sys.argv[1:]):
            return
        console.print(
            "[bold]Help improve InitRunner?[/bold] Send anonymous usage data (which command "
            "ran, version, OS, error type) to guide what to build next. No prompts, files, "
            "paths, arguments, or API keys are sent, and it is tied to a random id, not to you. "
            "Change anytime with [cyan]initrunner telemetry enable/disable[/cyan]."
        )
        granted = typer.confirm("Enable anonymous usage telemetry?", default=False)
        telemetry.set_consent(granted)
        if granted:
            telemetry.send_first_run()
    except (KeyboardInterrupt, EOFError, typer.Abort):
        # No decision: leave consent unset so we ask again next interactive run.
        return
    except Exception:
        import logging

        logging.getLogger(__name__).debug("telemetry consent prompt failed", exc_info=True)


def app_entry() -> None:
    """Entry point for the CLI.

    Wraps the Typer app so a single site captures the command outcome for
    anonymous telemetry. The opt-in consent prompt (if any) runs before the app,
    so nothing is sent until the user accepts, and the bounded flush guarantees a
    slow network never delays exit. All telemetry calls are best-effort and never
    raise.
    """
    import sys
    import time

    from initrunner import telemetry

    global _invoked_command
    _invoked_command = None  # main() sets it; reset so a bypassed callback falls back to argv

    start = time.monotonic()
    _maybe_prompt_telemetry_consent()

    status = "ok"
    exit_code: int | None = 0
    error_kind: str | None = None
    try:
        app()
    except SystemExit as exc:
        code = exc.code
        exit_code = code if isinstance(code, int) else (0 if code is None else 1)
        status = "ok" if exit_code == 0 else "error"
        raise
    except BaseException as exc:
        status = "error"
        exit_code = 1
        error_kind = type(exc).__name__
        raise
    finally:
        telemetry.record_command(
            command=_resolve_command(),
            status=status,
            exit_code=exit_code,
            error_kind=error_kind,
            duration_ms=(time.monotonic() - start) * 1000.0,
            is_tty=sys.stdin.isatty(),
        )
        telemetry.flush()
