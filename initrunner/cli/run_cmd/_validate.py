"""Flag validation for the run command."""

from __future__ import annotations

from pathlib import Path

import typer

from initrunner.cli._helpers import console


def _validate_flags(
    *,
    daemon_mode: bool,
    serve_mode: bool,
    autonomous: bool,
    autopilot: bool,
    bot: str | None,
    output_format: str,
    no_stream: bool,
    interactive: bool,
    sense: bool,
    role_file: Path | None,
    prompt: str | None,
) -> str:
    """Validate mutual exclusivity and format flags. Returns effective output_format."""
    mode_flags = sum([daemon_mode or autopilot, serve_mode, autonomous, bool(bot)])
    if mode_flags > 1:
        console.print(
            "[red]Error:[/red] --daemon, --serve, --bot, --autonomous,"
            " and --autopilot are mutually exclusive."
        )
        raise typer.Exit(1)

    if bot and bot not in ("telegram", "discord"):
        console.print(f"[red]Error:[/red] --bot must be 'telegram' or 'discord', got '{bot}'.")
        raise typer.Exit(1)

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

    if role_file is not None and sense:
        console.print("[red]Error:[/red] --sense and a role_file are mutually exclusive.")
        raise typer.Exit(1)
    if sense and not prompt:
        console.print("[red]Error:[/red] --sense requires --prompt (-p).")
        raise typer.Exit(1)
    if sense and (daemon_mode or autopilot or serve_mode or bot):
        console.print(
            "[red]Error:[/red] --daemon, --autopilot, --serve,"
            " and --bot are not supported with --sense."
        )
        raise typer.Exit(1)

    return output_format


def _validate_ephemeral_flags(
    *,
    daemon_mode: bool,
    serve_mode: bool,
    autonomous: bool,
    autopilot: bool,
    dry_run: bool,
    save: Path | None,
    skill_dir: Path | None,
    report: Path | None,
    report_template: str,
    resume: bool,
    prompt: str | None,
    interactive: bool,
) -> None:
    """Reject flags that don't apply to ephemeral mode."""
    invalid = []
    if daemon_mode:
        invalid.append("--daemon")
    if autopilot:
        invalid.append("--autopilot")
    if serve_mode:
        invalid.append("--serve")
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
        console.print(f"[red]Error:[/red] {', '.join(invalid)} not supported with a role file.")
        raise typer.Exit(1)
