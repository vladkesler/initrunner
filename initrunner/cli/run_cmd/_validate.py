"""Flag validation for the run command."""

from __future__ import annotations

import enum
from pathlib import Path

import typer

from initrunner.cli._helpers import console

# ---------------------------------------------------------------------------
# Run mode resolution
# ---------------------------------------------------------------------------


@enum.unique
class RunMode(enum.Enum):
    STANDARD = "standard"
    DAEMON = "daemon"
    SERVE = "serve"
    BOT = "bot"


def _resolve_run_mode(
    *,
    daemon_mode: bool,
    autopilot: bool,
    serve_mode: bool,
    bot: str | None,
    autonomous: bool,
) -> RunMode:
    """Resolve mutually exclusive mode flags into a single RunMode.

    ``--autopilot`` subsumes ``--daemon`` (both map to DAEMON).
    ``--autonomous`` is a STANDARD-mode modifier, mutually exclusive with
    the long-running modes.
    """
    active: list[tuple[str, RunMode]] = []
    if daemon_mode or autopilot:
        flag = "--autopilot" if autopilot else "--daemon"
        active.append((flag, RunMode.DAEMON))
    if serve_mode:
        active.append(("--serve", RunMode.SERVE))
    if bot:
        active.append(("--bot", RunMode.BOT))
    if autonomous:
        active.append(("--autonomous", RunMode.STANDARD))

    if len(active) > 1:
        console.print(
            f"[red]Error:[/red] Cannot combine {active[0][0]} and {active[1][0]}."
            " Choose one run mode."
        )
        raise typer.Exit(1)

    return active[0][1] if active else RunMode.STANDARD


# ---------------------------------------------------------------------------
# Universal validation (runs before ephemeral / role branching)
# ---------------------------------------------------------------------------


def _validate_universal_flags(
    *,
    mode: RunMode,
    bot: str | None,
    output_format: str,
    no_stream: bool,
    interactive: bool,
    autonomous: bool,
    sense: bool,
    confirm_role: bool,
    role_dir: Path | None,
    role_file: Path | None,
    prompt: str | None,
    api_key: str | None,
    cors_origin: list[str] | None,
    allowed_users: list[str] | None,
    allowed_user_ids: list[str] | None,
    budget_timezone: str | None,
) -> str:
    """Validate flags that apply regardless of ephemeral vs role-file mode.

    Returns effective *output_format* (handles ``--no-stream`` deprecation).
    """
    # -- Bot platform --
    if bot and bot not in ("telegram", "discord"):
        console.print(f"[red]Error:[/red] --bot must be 'telegram' or 'discord', got '{bot}'.")
        raise typer.Exit(1)

    # -- Format --
    if output_format not in ("auto", "json", "text", "rich"):
        console.print(
            f"[red]Error:[/red] Unknown format '{output_format}'. Use: auto, json, text, rich"
        )
        raise typer.Exit(1)

    if no_stream:
        typer.echo("Warning: --no-stream is deprecated; use --format rich", err=True)
        if output_format == "auto":
            output_format = "rich"

    if output_format in ("json", "text") and interactive:
        console.print("[red]Error:[/red] --format json|text is not supported with -i.")
        raise typer.Exit(1)

    if output_format in ("json", "text") and autonomous:
        console.print("[red]Error:[/red] --format json|text is not supported with -a.")
        raise typer.Exit(1)

    # -- Sense conflicts --
    if role_file is not None and sense:
        console.print("[red]Error:[/red] --sense and a role_file are mutually exclusive.")
        raise typer.Exit(1)
    if sense and not prompt:
        console.print("[red]Error:[/red] --sense requires --prompt (-p).")
        raise typer.Exit(1)
    if sense and mode in (RunMode.DAEMON, RunMode.SERVE, RunMode.BOT):
        console.print(f"[red]Error:[/red] --sense is not supported with {mode.value} mode.")
        raise typer.Exit(1)

    # -- Sense-dependent flags --
    if confirm_role and not sense:
        console.print(
            "[red]Error:[/red] --confirm-role requires --sense."
            " It confirms the auto-selected role before running."
        )
        raise typer.Exit(1)
    if role_dir is not None and not sense:
        console.print(
            "[red]Error:[/red] --role-dir requires --sense."
            " It sets the directory to search when sensing."
        )
        raise typer.Exit(1)

    # -- Serve-only flags --
    if mode != RunMode.SERVE:
        serve_only = [f for f, v in [("--api-key", api_key), ("--cors-origin", cors_origin)] if v]
        if serve_only:
            console.print(
                f"[red]Error:[/red] {', '.join(serve_only)} only applies to --serve mode."
            )
            raise typer.Exit(1)

    # -- Bot-only flags --
    if mode != RunMode.BOT:
        bot_only = [
            f
            for f, v in [
                ("--allowed-users", allowed_users),
                ("--allowed-user-ids", allowed_user_ids),
            ]
            if v
        ]
        if bot_only:
            console.print(f"[red]Error:[/red] {', '.join(bot_only)} only applies to --bot mode.")
            raise typer.Exit(1)

    # -- Budget timezone --
    if budget_timezone and mode not in (RunMode.DAEMON, RunMode.BOT):
        console.print(
            "[red]Error:[/red] --budget-timezone only applies to"
            " --daemon, --autopilot, or --bot mode."
        )
        raise typer.Exit(1)

    return output_format


# ---------------------------------------------------------------------------
# Ephemeral-only validation
# ---------------------------------------------------------------------------


def _validate_ephemeral_flags(
    *,
    mode: RunMode,
    autonomous: bool,
    dry_run: bool,
    save: Path | None,
    skill_dir: Path | None,
    report: Path | None,
    report_template: str,
    resume: bool,
    prompt: str | None,
    interactive: bool,
) -> None:
    """Reject flags that don't apply to ephemeral mode (no role file)."""
    if mode not in (RunMode.STANDARD, RunMode.BOT):
        console.print(f"[red]Error:[/red] {mode.value} mode is not supported without a role file.")
        raise typer.Exit(1)

    invalid = []
    if autonomous:
        invalid.append("--autonomous")
    if dry_run:
        invalid.append("--dry-run")
    if save is not None:
        invalid.append("--save")
    if skill_dir is not None:
        invalid.append("--skill-dir")
    if report is not None:
        invalid.append("--report")
    if report_template != "default":
        invalid.append("--report-template")
    if invalid:
        console.print(f"[red]Error:[/red] {', '.join(invalid)} not supported without a role file.")
        raise typer.Exit(1)

    # --resume only valid for REPL (no -p, or -p with -i)
    if resume and prompt and not interactive:
        console.print("[red]Error:[/red] --resume requires -i when used with -p.")
        raise typer.Exit(1)


# ---------------------------------------------------------------------------
# Role-file-only validation
# ---------------------------------------------------------------------------


def _validate_role_only_flags(
    *,
    tool_profile: str | None,
    extra_tools: list[str] | None,
    provider: str | None,
    ingest: list[str] | None,
    list_tools: bool,
) -> None:
    """Reject ephemeral-only flags when a role file is provided."""
    invalid = []
    if tool_profile is not None:
        invalid.append("--tool-profile")
    if extra_tools:
        invalid.append("--tools")
    if provider is not None:
        invalid.append("--provider")
    if ingest:
        invalid.append("--ingest")
    if list_tools:
        invalid.append("--list-tools")
    if invalid:
        console.print(
            f"[red]Error:[/red] {', '.join(invalid)} not supported with a role file"
            " (these settings come from the YAML)."
        )
        raise typer.Exit(1)
