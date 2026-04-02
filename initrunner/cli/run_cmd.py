"""Run command: unified dispatcher for agent, team, compose, and ephemeral modes."""

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
# Starter listing & save
# ---------------------------------------------------------------------------


def _show_starter_listing() -> None:
    """Render a Rich table of available starter agents."""
    from rich.table import Table

    from initrunner.services.starters import check_prerequisites, list_starters

    starters = list_starters()
    if not starters:
        console.print("[dim]No starter agents found.[/dim]")
        return

    table = Table(title="Starter Agents", show_lines=False, pad_edge=False)
    table.add_column("Name", style="cyan", no_wrap=True)
    table.add_column("Kind", style="dim")
    table.add_column("Description")
    table.add_column("Features", style="green")
    table.add_column("Status")

    for entry in starters:
        errors, _warnings = check_prerequisites(entry)
        if errors:
            status = f"[yellow]{errors[0]}[/yellow]"
        else:
            status = "[green]Ready[/green]"

        desc = entry.description
        if len(desc) > 50:
            desc = desc[:47] + "..."

        table.add_row(
            entry.slug,
            entry.kind,
            desc,
            " ".join(entry.features),
            status,
        )

    console.print()
    console.print(table)
    console.print()
    console.print("[dim]Usage:[/dim]")
    console.print("  initrunner run <name>              Run interactively")
    console.print('  initrunner run <name> -p "..."      Single-shot with prompt')
    console.print("  initrunner run <name> --save .      Copy to local directory for customization")
    console.print()


def _handle_save(role_file: Path, save_dir: Path) -> None:
    """Copy a starter to a local directory."""
    import shutil

    from initrunner.services.starters import STARTERS_DIR

    try:
        if not role_file.resolve().is_relative_to(STARTERS_DIR.resolve()):
            console.print("[red]Error:[/red] --save only works with bundled starters.")
            raise typer.Exit(1)
    except ValueError:
        console.print("[red]Error:[/red] --save only works with bundled starters.")
        raise typer.Exit(1) from None

    starter_dir = role_file.parent
    save_dir.mkdir(parents=True, exist_ok=True)

    if starter_dir.resolve() == STARTERS_DIR.resolve():
        # Single-file starter
        dest = save_dir / "role.yaml"
        shutil.copy2(role_file, dest)
        console.print(f"[green]Copied[/green] {role_file.name} to {dest}")
    else:
        # Composite starter (subdirectory)
        for item in starter_dir.iterdir():
            src = starter_dir / item.name
            dst = save_dir / item.name
            if src.is_dir():
                shutil.copytree(src, dst, dirs_exist_ok=True)
            else:
                shutil.copy2(src, dst)
        console.print(f"[green]Copied[/green] {starter_dir.name}/ to {save_dir}")

    console.print()
    console.print("[dim]Next steps:[/dim]")
    edit_target = save_dir / "role.yaml" if (save_dir / "role.yaml").exists() else save_dir
    console.print(f"  1. Edit {edit_target}")
    console.print(f"  2. initrunner run {save_dir} -i")
    console.print()


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
    *,
    autopilot: bool = False,
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
            autopilot=autopilot,
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
        typer.Argument(help="YAML file, directory, or name. Omit for ephemeral mode."),
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
    save: Annotated[
        Path | None,
        typer.Option("--save", help="Copy starter to local directory for customization"),
    ] = None,
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
    autopilot: Annotated[
        bool, typer.Option("--autopilot", help="Daemon mode with all triggers autonomous")
    ] = False,
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
    # --- Ephemeral mode options ---
    provider: Annotated[
        str | None,
        typer.Option(
            "--provider",
            help="Model provider (ephemeral mode)",
            rich_help_panel="Ephemeral Mode",
        ),
    ] = None,
    tool_profile: Annotated[
        str | None,
        typer.Option(
            "--tool-profile",
            help="Tool profile: minimal, all, none",
            rich_help_panel="Ephemeral Mode",
        ),
    ] = None,
    extra_tools: Annotated[
        list[str] | None,
        typer.Option(
            "--tools",
            help="Extra tool types (repeatable)",
            rich_help_panel="Ephemeral Mode",
        ),
    ] = None,
    list_tools: Annotated[
        bool,
        typer.Option(
            "--list-tools",
            help="List available extra tool types and exit",
            rich_help_panel="Ephemeral Mode",
        ),
    ] = False,
    memory: Annotated[
        bool | None,
        typer.Option(
            "--memory/--no-memory",
            help="Enable/disable persistent memory",
            rich_help_panel="Ephemeral Mode",
        ),
    ] = None,
    ingest: Annotated[
        list[str] | None,
        typer.Option(
            "--ingest",
            help="Paths/globs to ingest for RAG (repeatable)",
            rich_help_panel="Ephemeral Mode",
        ),
    ] = None,
    list_starters: Annotated[
        bool,
        typer.Option("--list", help="List available starter agents"),
    ] = False,
) -> None:
    """Run an agent from a YAML file, starter name, or ephemeral mode.

    Without a role file, starts an ephemeral REPL with auto-detected provider.
    Use --list to see available starter agents.
    """
    # --- --list: show starters ---
    if list_starters:
        _show_starter_listing()
        raise typer.Exit(0)

    # --- --list-tools: show ephemeral tool types ---
    if list_tools:
        from initrunner.cli._ephemeral import print_list_tools

        print_list_tools()
        raise typer.Exit(0)

    # --- No role file + no --sense: ephemeral mode ---
    if role_file is None and not sense:
        _validate_ephemeral_flags(
            daemon_mode=daemon_mode,
            serve_mode=serve_mode,
            autonomous=autonomous,
            autopilot=autopilot,
            dry_run=dry_run,
            save=save,
            skill_dir=skill_dir,
            report=report,
            report_template=report_template,
            resume=resume,
            prompt=prompt,
            interactive=interactive,
        )
        from initrunner.cli._ephemeral import dispatch_ephemeral

        dispatch_ephemeral(
            provider=provider,
            model=model,
            prompt=prompt,
            interactive=interactive,
            tool_profile=tool_profile,
            extra_tools=extra_tools,
            memory=memory,
            resume=resume,
            ingest=ingest,
            bot=bot,
            attach=attach,
            allowed_users=allowed_users,
            allowed_user_ids=allowed_user_ids,
            audit_db=audit_db,
            no_audit=no_audit,
        )
        return

    # --- Role-incompatible flags ---
    _validate_role_only_flags(
        tool_profile=tool_profile,
        extra_tools=extra_tools,
        provider=provider,
        ingest=ingest,
        list_tools=list_tools,
    )

    # --- Validate flags ---
    output_format = _validate_flags(
        daemon_mode=daemon_mode,
        serve_mode=serve_mode,
        autonomous=autonomous,
        autopilot=autopilot,
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

    # --- --save: copy starter to local directory (no prerequisites needed) ---
    if save is not None:
        _handle_save(role_file, save)
        return

    # --- Starter: prerequisites + model auto-detect ---
    from initrunner.cli._helpers import prepare_starter

    effective_model = prepare_starter(role_file, model) or model

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
        if autopilot:
            invalid.append("--autopilot")
        if serve_mode:
            invalid.append("--serve")
        if bot:
            invalid.append("--bot")
        if invalid:
            console.print(
                f"[red]Error:[/red] {', '.join(invalid)} not supported for Compose targets."
            )
            raise typer.Exit(1)

    if kind not in ("Agent",) and (daemon_mode or autopilot or serve_mode or bot):
        console.print(
            "[red]Error:[/red] --daemon, --autopilot, --serve,"
            " and --bot are only supported for Agent targets."
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
            role_file,
            host,
            port,
            api_key,
            cors_origin,
            audit_db,
            no_audit,
            skill_dir,
            effective_model,
        )
        return

    if bot:
        _dispatch_bot(
            role_file,
            bot,
            allowed_users,
            allowed_user_ids,
            audit_db,
            no_audit,
            skill_dir,
            effective_model,
        )
        return

    if daemon_mode or autopilot:
        _dispatch_daemon(
            role_file, audit_db, no_audit, skill_dir, effective_model, autopilot=autopilot
        )
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
        model=effective_model,
    )
