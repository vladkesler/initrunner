"""The ``run`` Typer command: parameter definitions and dispatch body."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from initrunner.cli._helpers import (
    console,
    preflight_validate_or_exit,
    resolve_run_target,
)
from initrunner.cli._options import AuditDbOption, ModelOption, NoAuditOption, SkillDirOption
from initrunner.cli._run_agent import _run_agent
from initrunner.cli._run_team import _run_team
from initrunner.cli.run_cmd._dispatch import (
    _dispatch_bot,
    _dispatch_daemon,
    _dispatch_flow,
    _dispatch_serve,
)
from initrunner.cli.run_cmd._sensing import _resolve_via_sensing
from initrunner.cli.run_cmd._starters import _handle_save, _show_starter_listing
from initrunner.cli.run_cmd._validate import (
    RunMode,
    _resolve_run_mode,
    _validate_ephemeral_flags,
    _validate_role_only_flags,
    _validate_universal_flags,
)


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
    budget_timezone: Annotated[
        str | None,
        typer.Option(
            "--budget-timezone",
            help="IANA timezone for daily budget reset (e.g. America/New_York)",
            rich_help_panel="Daemon Options",
        ),
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
            help=(
                "Tool profile: none, minimal (datetime, web_reader),"
                " all (+ search, python, filesystem, git, shell, slack)"
            ),
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
    explain_profiles: Annotated[
        bool,
        typer.Option(
            "--explain-profiles",
            help="Show tools in each tool profile and exit",
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

    # --- --explain-profiles: show tool profile breakdown ---
    if explain_profiles:
        from initrunner.cli._ephemeral import print_explain_profiles

        print_explain_profiles()
        raise typer.Exit(0)

    # --- Universal validation (before ephemeral / role branching) ---
    mode = _resolve_run_mode(
        daemon_mode=daemon_mode,
        autopilot=autopilot,
        serve_mode=serve_mode,
        bot=bot,
        autonomous=autonomous,
    )
    output_format = _validate_universal_flags(
        mode=mode,
        bot=bot,
        output_format=output_format,
        no_stream=no_stream,
        interactive=interactive,
        autonomous=autonomous,
        sense=sense,
        confirm_role=confirm_role,
        role_dir=role_dir,
        role_file=role_file,
        prompt=prompt,
        api_key=api_key,
        cors_origin=cors_origin,
        allowed_users=allowed_users,
        allowed_user_ids=allowed_user_ids,
        budget_timezone=budget_timezone,
    )

    # --- No role file + no --sense: ephemeral mode ---
    if role_file is None and not sense:
        _validate_ephemeral_flags(
            mode=mode,
            autonomous=autonomous,
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
            "Use Team for one-shot multi-agent workflows, or Flow for long-running agents."
        )
        raise typer.Exit(1)

    # --- Kind-specific flag validation ---
    if kind == "Flow":
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
        if mode != RunMode.STANDARD:
            invalid.append(f"--{mode.value}" if mode != RunMode.DAEMON else "--daemon/--autopilot")
        if invalid:
            console.print(f"[red]Error:[/red] {', '.join(invalid)} not supported for Flow targets.")
            raise typer.Exit(1)

    if kind not in ("Agent",) and mode != RunMode.STANDARD:
        console.print(f"[red]Error:[/red] {mode.value} mode is only supported for Agent targets.")
        raise typer.Exit(1)

    # --- Pre-flight YAML validation: catch syntax/schema errors before any
    #     skill resolution, model resolution, or API calls.  Covers all
    #     downstream dispatches (Agent/Team/Flow, serve/bot/daemon).  Runs
    #     after the cheap flag checks above so flag errors fire first.
    preflight_validate_or_exit(role_file)

    # --- Kind-based dispatch ---
    if kind == "Team":
        _run_team(role_file, prompt, dry_run, audit_db, no_audit, report, report_template)
        return

    if kind == "Flow":
        _dispatch_flow(role_file, audit_db, no_audit)
        return

    # --- Agent mode: flag-based dispatch ---
    if mode == RunMode.SERVE:
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

    if mode == RunMode.BOT:
        _dispatch_bot(
            role_file,
            bot,
            allowed_users,
            allowed_user_ids,
            audit_db,
            no_audit,
            skill_dir,
            effective_model,
            budget_timezone=budget_timezone,
        )
        return

    if mode == RunMode.DAEMON:
        _dispatch_daemon(
            role_file,
            audit_db,
            no_audit,
            skill_dir,
            effective_model,
            autopilot=autopilot,
            budget_timezone=budget_timezone,
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
