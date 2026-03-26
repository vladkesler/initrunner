"""Run command: unified dispatcher for agent, team, and compose modes."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated

import typer

from initrunner.cli._helpers import (
    command_context,
    console,
    create_audit_logger,
    resolve_model_override,
    resolve_run_target,
    resolve_skill_dirs,
)
from initrunner.cli._options import AuditDbOption, ModelOption, NoAuditOption, SkillDirOption
from initrunner.cli._run_agent import _run_agent
from initrunner.cli._run_team import _run_team


def _validate_flags(
    *,
    daemon_mode: bool,
    serve_mode: bool,
    autonomous: bool,
    bot: str | None,
    output_format: str,
    no_stream: bool,
    interactive: bool,
    sense: bool,
    role_file: Path | None,
    prompt: str | None,
) -> str:
    """Validate mutual exclusivity and format flags. Returns effective output_format."""
    mode_flags = sum([daemon_mode, serve_mode, autonomous, bool(bot)])
    if mode_flags > 1:
        console.print(
            "[red]Error:[/red] --daemon, --serve, --bot, and --autonomous are mutually exclusive."
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
    if role_file is None and not sense:
        console.print(
            "[red]Error:[/red] Provide a role file, installed role name, or use --sense.\n"
            "[dim]Hint: for quick ephemeral chat, use 'initrunner chat'.\n"
            "      To create a new agent, use 'initrunner new'.[/dim]"
        )
        raise typer.Exit(1)
    if sense and not prompt:
        console.print("[red]Error:[/red] --sense requires --prompt (-p).")
        raise typer.Exit(1)

    return output_format


def _resolve_via_sensing(
    prompt: str,
    *,
    role_dir: Path | None,
    confirm_role: bool,
    dry_run: bool,
) -> Path:
    """Run intent sensing to find the best role. Returns resolved role path."""
    from initrunner.cli._helpers import display_sense_result
    from initrunner.services.role_selector import NoRolesFoundError, select_role_sync

    try:
        with console.status("[dim]Sensing best role...[/dim]"):
            selection = select_role_sync(
                prompt,
                role_dir=role_dir,
                allow_llm=not dry_run,
            )
    except (NoRolesFoundError, ValueError) as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1) from None
    display_sense_result(selection)
    if confirm_role:
        if not sys.stdin.isatty():
            console.print("[red]Error:[/red] --confirm-role requires an interactive terminal.")
            raise typer.Exit(1)
        if not typer.confirm("Use this role?", default=True):
            raise typer.Exit()
    return selection.candidate.path


# ---------------------------------------------------------------------------
# Small dispatch helpers that stay here (direct callees of run())
# ---------------------------------------------------------------------------


def _dispatch_compose(compose_file: Path, audit_db: Path | None, no_audit: bool) -> None:
    """Run a compose file (foreground)."""
    from initrunner.compose.loader import ComposeLoadError
    from initrunner.services.compose import load_compose_sync, run_compose_sync

    try:
        compose = load_compose_sync(compose_file)
    except ComposeLoadError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1) from None

    audit_logger = create_audit_logger(audit_db, no_audit)

    try:
        run_compose_sync(compose, compose_file.parent, audit_logger=audit_logger)
    finally:
        if audit_logger is not None:
            audit_logger.close()


def _dispatch_serve(
    role_file: Path,
    host: str,
    port: int,
    api_key: str | None,
    cors_origin: list[str] | None,
    audit_db: Path | None,
    no_audit: bool,
    skill_dir: Path | None,
    model: str | None,
) -> None:
    """Serve an agent as an OpenAI-compatible API."""
    from initrunner.server.app import run_server

    resolved_model = resolve_model_override(model)
    with command_context(
        role_file,
        audit_db=audit_db,
        no_audit=no_audit,
        extra_skill_dirs=resolve_skill_dirs(skill_dir),
        model_override=resolved_model,
    ) as (role, agent, audit_logger, _memory_store, _sink_dispatcher):
        console.print(f"Serving [cyan]{role.metadata.name}[/cyan] at http://{host}:{port}")
        console.print(f"  Model ID: {role.metadata.name}")
        console.print(f"  Health:   http://{host}:{port}/health")
        console.print(f"  Models:   http://{host}:{port}/v1/models")
        if api_key:
            console.print("  Auth:     [yellow]enabled[/yellow] (Bearer token required)")
        if cors_origin:
            console.print(f"  CORS:     {', '.join(cors_origin)}")

        run_server(
            agent,
            role,
            host=host,
            port=port,
            audit_logger=audit_logger,
            api_key=api_key,
            cors_origins=cors_origin,
        )


def _dispatch_daemon(
    role_file: Path,
    audit_db: Path | None,
    no_audit: bool,
    skill_dir: Path | None,
    model: str | None,
) -> None:
    """Run agent in daemon mode with triggers."""
    from initrunner.runner import run_daemon

    resolved_model = resolve_model_override(model)
    extra_skill_dirs = resolve_skill_dirs(skill_dir)
    with command_context(
        role_file,
        audit_db=audit_db,
        no_audit=no_audit,
        with_memory=True,
        with_sinks=True,
        extra_skill_dirs=extra_skill_dirs,
        model_override=resolved_model,
    ) as (role, agent, audit_logger, memory_store, sink_dispatcher):
        run_daemon(
            agent,
            role,
            audit_logger=audit_logger,
            sink_dispatcher=sink_dispatcher,
            memory_store=memory_store,
            role_path=role_file.resolve(),
            extra_skill_dirs=extra_skill_dirs,
        )


def _dispatch_bot(
    role_file: Path,
    platform: str,
    allowed_users: list[str] | None,
    allowed_user_ids: list[str] | None,
    audit_db: Path | None,
    no_audit: bool,
    skill_dir: Path | None,
    model: str | None,
) -> None:
    """Launch an agent as a Telegram or Discord bot."""
    from initrunner.runner import run_bot

    resolved_model = resolve_model_override(model)
    with command_context(
        role_file,
        audit_db=audit_db,
        no_audit=no_audit,
        with_memory=True,
        with_sinks=True,
        extra_skill_dirs=resolve_skill_dirs(skill_dir),
        model_override=resolved_model,
    ) as (role, agent, audit_logger, memory_store, sink_dispatcher):
        run_bot(
            agent,
            role,
            platform,
            allowed_users=allowed_users,
            allowed_user_ids=allowed_user_ids,
            audit_logger=audit_logger,
            sink_dispatcher=sink_dispatcher,
            memory_store=memory_store,
        )


# ---------------------------------------------------------------------------
# Main run command
# ---------------------------------------------------------------------------


def run(
    role_file: Annotated[
        Path | None,
        typer.Argument(help="Agent/Team/Compose YAML, directory, or name. Omit with --sense."),
    ] = None,
    prompt: Annotated[str | None, typer.Option("-p", "--prompt", help="Prompt to send")] = None,
    interactive: Annotated[
        bool, typer.Option("-i", "--interactive", help="Interactive REPL mode")
    ] = False,
    autonomous: Annotated[
        bool, typer.Option("-a", "--autonomous", help="Autonomous agentic loop mode")
    ] = False,
    max_iterations: Annotated[
        int | None,
        typer.Option("--max-iterations", help="Override max iterations for autonomous mode"),
    ] = None,
    resume: Annotated[bool, typer.Option("--resume", help="Resume previous REPL session")] = False,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Simulate with TestModel (no API calls)")
    ] = False,
    audit_db: AuditDbOption = None,
    no_audit: NoAuditOption = False,
    skill_dir: SkillDirOption = None,
    attach: Annotated[
        list[str] | None,
        typer.Option(
            "--attach",
            "-A",
            help="Attach file or URL (repeatable, supports images/audio/video/docs)",
        ),
    ] = None,
    report: Annotated[
        Path | None,
        typer.Option("--report", help="Export markdown report to PATH after run"),
    ] = None,
    report_template: Annotated[
        str,
        typer.Option(
            "--report-template",
            help="Report template: default, pr-review, changelog, ci-fix",
        ),
    ] = "default",
    output_format: Annotated[
        str,
        typer.Option("-f", "--format", help="Output format: auto, json, text, rich"),
    ] = "auto",
    no_stream: Annotated[
        bool, typer.Option("--no-stream", hidden=True, help="Deprecated: use --format rich")
    ] = False,
    sense: Annotated[
        bool, typer.Option("--sense", help="Sense the best role for the given prompt")
    ] = False,
    role_dir: Annotated[
        Path | None,
        typer.Option("--role-dir", help="Directory to search for roles (used with --sense)"),
    ] = None,
    confirm_role: Annotated[
        bool,
        typer.Option("--confirm-role", help="Confirm auto-selected role before running"),
    ] = False,
    model: ModelOption = None,
    # --- Mode flags ---
    daemon_mode: Annotated[
        bool, typer.Option("--daemon", help="Run in daemon mode with triggers")
    ] = False,
    serve_mode: Annotated[
        bool, typer.Option("--serve", help="Serve as OpenAI-compatible API")
    ] = False,
    bot: Annotated[
        str | None, typer.Option("--bot", help="Launch as bot (telegram or discord)")
    ] = None,
    # --- Serve options ---
    host: Annotated[
        str, typer.Option(help="Host to bind to", rich_help_panel="Serve Options")
    ] = "127.0.0.1",
    port: Annotated[
        int, typer.Option(help="Port to listen on", rich_help_panel="Serve Options")
    ] = 8000,
    api_key: Annotated[
        str | None,
        typer.Option("--api-key", help="API key for auth", rich_help_panel="Serve Options"),
    ] = None,
    cors_origin: Annotated[
        list[str] | None,
        typer.Option(
            "--cors-origin", help="CORS origin (repeatable)", rich_help_panel="Serve Options"
        ),
    ] = None,
    # --- Bot options ---
    allowed_users: Annotated[
        list[str] | None,
        typer.Option("--allowed-users", help="Bot username filter", rich_help_panel="Bot Options"),
    ] = None,
    allowed_user_ids: Annotated[
        list[str] | None,
        typer.Option(
            "--allowed-user-ids",
            help="Bot user ID filter (repeatable)",
            rich_help_panel="Bot Options",
        ),
    ] = None,
) -> None:
    """Run an agent, team, or compose from a YAML file.

    Use -i for interactive REPL, -a for autonomous mode.
    For quick chat without a role file, use 'initrunner chat'.
    """
    # --- Validate flags ---
    output_format = _validate_flags(
        daemon_mode=daemon_mode,
        serve_mode=serve_mode,
        autonomous=autonomous,
        bot=bot,
        output_format=output_format,
        no_stream=no_stream,
        interactive=interactive,
        sense=sense,
        role_file=role_file,
        prompt=prompt,
    )

    # --- Intent sensing ---
    if sense:
        role_file = _resolve_via_sensing(
            prompt,  # type: ignore[arg-type]  # guarded by _validate_flags
            role_dir=role_dir,
            confirm_role=confirm_role,
            dry_run=dry_run,
        )

    # --- Resolve target and detect kind ---
    if role_file is None:
        raise RuntimeError("role_file unresolved")

    resolved, kind = resolve_run_target(role_file)
    role_file = resolved

    # --- Removed kind rejection ---
    if kind == "Pipeline":
        console.print(
            "[red]Error:[/red] kind: Pipeline has been removed.\n"
            "Use Team for one-shot multi-agent workflows, or Compose for long-running services."
        )
        raise typer.Exit(1)

    # --- Kind-specific flag validation ---
    if kind == "Compose":
        invalid = []
        if prompt:
            invalid.append("--prompt")
        if interactive:
            invalid.append("--interactive")
        if autonomous:
            invalid.append("--autonomous")
        if resume:
            invalid.append("--resume")
        if attach:
            invalid.append("--attach")
        if report:
            invalid.append("--report")
        if sense:
            invalid.append("--sense")
        if daemon_mode:
            invalid.append("--daemon")
        if serve_mode:
            invalid.append("--serve")
        if bot:
            invalid.append("--bot")
        if invalid:
            console.print(
                f"[red]Error:[/red] {', '.join(invalid)} not supported for Compose targets."
            )
            raise typer.Exit(1)

    if kind not in ("Agent",) and (daemon_mode or serve_mode or bot):
        console.print(
            "[red]Error:[/red] --daemon, --serve, and --bot are only supported for Agent targets."
        )
        raise typer.Exit(1)

    # --- Kind-based dispatch ---
    if kind == "Team":
        _run_team(role_file, prompt, dry_run, audit_db, no_audit, report, report_template)
        return

    if kind == "Compose":
        _dispatch_compose(role_file, audit_db, no_audit)
        return

    # --- Agent mode: flag-based dispatch ---
    if serve_mode:
        _dispatch_serve(
            role_file, host, port, api_key, cors_origin, audit_db, no_audit, skill_dir, model
        )
        return

    if bot:
        _dispatch_bot(
            role_file, bot, allowed_users, allowed_user_ids, audit_db, no_audit, skill_dir, model
        )
        return

    if daemon_mode:
        _dispatch_daemon(role_file, audit_db, no_audit, skill_dir, model)
        return

    # --- Standard agent execution ---
    _run_agent(
        role_file,
        prompt=prompt,
        interactive=interactive,
        autonomous=autonomous,
        max_iterations=max_iterations,
        resume=resume,
        dry_run=dry_run,
        audit_db=audit_db,
        no_audit=no_audit,
        skill_dir=skill_dir,
        attach=attach,
        report=report,
        report_template=report_template,
        output_format=output_format,
        no_stream=no_stream,
        model=model,
    )
