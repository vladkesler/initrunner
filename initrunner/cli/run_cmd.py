"""Run commands: run, test, ingest."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING, Annotated

import typer
from rich.table import Table

from initrunner.cli._helpers import (
    command_context,
    console,
    create_audit_logger,
    load_and_build_or_exit,
    load_role_or_exit,
    resolve_model_override,
    resolve_role_path,
    resolve_run_target,
    resolve_skill_dirs,
)
from initrunner.cli._options import AuditDbOption, ModelOption, NoAuditOption, SkillDirOption

if TYPE_CHECKING:
    from initrunner.agent.executor import AutonomousResult, RunResult
    from initrunner.agent.prompt import UserPrompt
    from initrunner.agent.schema.role import RoleDefinition


def _maybe_export_report(
    role: RoleDefinition,
    result: RunResult | AutonomousResult,
    prompt: UserPrompt | None,
    output_path: Path,
    template_name: str,
    dry_run: bool,
) -> None:
    """Try to export a report; warn on failure, never crash."""
    try:
        from initrunner.agent.prompt import extract_text_from_prompt
        from initrunner.report import export_report

        prompt_text = extract_text_from_prompt(prompt or "")
        path = export_report(
            role, result, prompt_text, output_path, template_name=template_name, dry_run=dry_run
        )
        console.print(f"[green]Report exported:[/green] {path}")
    except Exception as e:
        console.print(f"[yellow]Warning:[/yellow] Report export failed: {e}")


def run(
    role_file: Annotated[
        Path | None,
        typer.Argument(
            help="Agent/Team/Compose/Pipeline YAML, directory, or name. Omit with --sense."
        ),
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
    no_stream: Annotated[
        bool, typer.Option("--no-stream", help="Disable streaming output (show result in panel)")
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
    # --- Pipeline options ---
    var: Annotated[
        list[str] | None,
        typer.Option(
            "--var", help="Pipeline variable key=value", rich_help_panel="Pipeline Options"
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
    """Run an agent, team, compose, or pipeline target."""

    # --- Mutual exclusivity for mode flags ---
    mode_flags = sum([daemon_mode, serve_mode, autonomous, bool(bot)])
    if mode_flags > 1:
        console.print(
            "[red]Error:[/red] --daemon, --serve, --bot, and --autonomous are mutually exclusive."
        )
        raise typer.Exit(1)

    if bot and bot not in ("telegram", "discord"):
        console.print(f"[red]Error:[/red] --bot must be 'telegram' or 'discord', got '{bot}'.")
        raise typer.Exit(1)

    # --- Intent Sensing resolution ---
    if role_file is not None and sense:
        console.print("[red]Error:[/red] --sense and a role_file are mutually exclusive.")
        raise typer.Exit(1)
    if role_file is None and not sense:
        console.print(
            "[red]Error:[/red] Provide a target file, installed role name, or use --sense."
        )
        raise typer.Exit(1)
    if sense and not prompt:
        console.print("[red]Error:[/red] --sense requires --prompt (-p).")
        raise typer.Exit(1)

    if sense:
        from initrunner.cli._helpers import display_sense_result
        from initrunner.services.role_selector import NoRolesFoundError, select_role_sync

        try:
            with console.status("[dim]Sensing best role...[/dim]"):
                selection = select_role_sync(
                    prompt,  # type: ignore[arg-type]  # guarded by sense+prompt check above
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
        role_file = selection.candidate.path
    # --- End Intent Sensing ---

    # --- Resolve target and detect kind ---
    if role_file is None:
        raise RuntimeError("role_file unresolved")

    resolved, kind = resolve_run_target(role_file)
    role_file = resolved

    # --- Kind-specific flag validation ---
    if kind in ("Compose", "Pipeline"):
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
                f"[red]Error:[/red] {', '.join(invalid)} not supported for {kind} targets."
            )
            raise typer.Exit(1)

    if kind != "Pipeline" and var:
        console.print("[red]Error:[/red] --var is only supported for Pipeline targets.")
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

    if kind == "Pipeline":
        _dispatch_pipeline(role_file, var, dry_run, audit_db, no_audit)
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
            model,
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
            model,
        )
        return

    if daemon_mode:
        _dispatch_daemon(role_file, audit_db, no_audit, skill_dir, model)
        return

    # --- Standard Agent execution (single-shot / REPL / autonomous) ---
    if autonomous and not prompt:
        console.print("[red]Error:[/red] --autonomous requires --prompt (-p).")
        raise typer.Exit(1)
    if autonomous and interactive:
        console.print("[red]Error:[/red] --autonomous and --interactive are mutually exclusive.")
        raise typer.Exit(1)

    if report_template != "default" and report is None:
        console.print("[red]Error:[/red] --report-template requires --report PATH.")
        raise typer.Exit(1)

    if report is not None:
        from initrunner.report import BUILT_IN_TEMPLATES

        if report_template not in BUILT_IN_TEMPLATES:
            console.print(
                f"[red]Error:[/red] Unknown template '{report_template}'. "
                f"Available: {', '.join(BUILT_IN_TEMPLATES)}"
            )
            raise typer.Exit(1)

    if attach and not prompt and not interactive and sys.stdin.isatty():
        console.print("[red]Error:[/red] use --prompt with --attach or pipe stdin.")
        raise typer.Exit(1)

    from initrunner.runner import run_autonomous, run_interactive, run_single, run_single_stream

    model_override = None
    if dry_run:
        from pydantic_ai.models.test import TestModel

        model_override = TestModel(
            custom_output_text="[dry-run] Simulated response.", call_tools=[]
        )

    # Build multimodal prompt if attachments provided
    user_prompt = prompt
    if attach and prompt:
        from initrunner.agent.prompt import build_multimodal_prompt

        try:
            user_prompt = build_multimodal_prompt(prompt, attach)
        except (FileNotFoundError, ValueError) as e:
            console.print(f"[red]Attachment error:[/red] {e}")
            raise typer.Exit(1) from None

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
        # Trigger hint for REPL mode
        if (
            not prompt
            and not autonomous
            and not daemon_mode
            and not serve_mode
            and not bot
            and role.spec.triggers
        ):
            console.print(
                "[dim]Hint: this role has triggers. Use --daemon to run in daemon mode.[/dim]"
            )

        message_history = None
        run_result = None  # RunResult or AutonomousResult

        use_stream = (
            sys.stdout.isatty()
            and not no_stream
            and not autonomous
            and role.spec.output.type == "text"
        )
        _run_single = run_single_stream if use_stream else run_single

        if autonomous:
            if user_prompt is None:
                raise RuntimeError("prompt unresolved")
            run_result = run_autonomous(
                agent,
                role,
                user_prompt,
                audit_logger=audit_logger,
                sink_dispatcher=sink_dispatcher,
                memory_store=memory_store,
                model_override=model_override,
                max_iterations_override=max_iterations,
            )
        elif user_prompt and not interactive:
            run_result, _ = _run_single(
                agent,
                role,
                user_prompt,
                audit_logger=audit_logger,
                sink_dispatcher=sink_dispatcher,
                model_override=model_override,
            )
        elif user_prompt and interactive:
            run_result, message_history = _run_single(
                agent,
                role,
                user_prompt,
                audit_logger=audit_logger,
                sink_dispatcher=sink_dispatcher,
                model_override=model_override,
            )
            if report is not None:
                _maybe_export_report(
                    role, run_result, user_prompt, report, report_template, dry_run
                )
            run_interactive(
                agent,
                role,
                audit_logger=audit_logger,
                message_history=message_history,
                memory_store=memory_store,
                resume=False,
                sink_dispatcher=sink_dispatcher,
                model_override=model_override,
                stream=use_stream,
            )
        else:
            run_interactive(
                agent,
                role,
                audit_logger=audit_logger,
                memory_store=memory_store,
                resume=resume,
                sink_dispatcher=sink_dispatcher,
                model_override=model_override,
                stream=use_stream,
            )

        # Export for non-interactive branches (after run completes)
        if report is not None and run_result is not None and not (user_prompt and interactive):
            _maybe_export_report(role, run_result, user_prompt, report, report_template, dry_run)


# ---------------------------------------------------------------------------
# Dispatch helpers for non-Agent kinds and Agent mode flags
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


def _dispatch_pipeline(
    pipeline_file: Path,
    var: list[str] | None,
    dry_run: bool,
    audit_db: Path | None,
    no_audit: bool,
) -> None:
    """Run a pipeline file."""
    from initrunner.pipeline.loader import PipelineLoadError, load_pipeline

    try:
        pipe = load_pipeline(pipeline_file)
    except PipelineLoadError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1) from None

    variables: dict[str, str] = {}
    for v in var or []:
        if "=" not in v:
            console.print(f"[red]Error:[/red] Invalid variable format: '{v}'. Use key=value.")
            raise typer.Exit(1)
        key, value = v.split("=", 1)
        variables[key] = value

    if dry_run:
        from initrunner.cli.server_cmd import _display_pipeline_dry_run

        _display_pipeline_dry_run(pipe, variables)
        return

    audit_logger = create_audit_logger(audit_db, no_audit)

    try:
        from initrunner.pipeline.executor import run_pipeline

        result = run_pipeline(
            pipe,
            variables=variables,
            audit_logger=audit_logger,
            base_dir=pipeline_file.parent,
        )
        from initrunner.cli.server_cmd import _display_pipeline_result

        _display_pipeline_result(result)

        if not result.success:
            raise typer.Exit(1)
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


def _display_team_result(team_result: object) -> None:
    """Display team run results."""
    from rich.markdown import Markdown
    from rich.panel import Panel

    from initrunner.team.runner import TeamResult

    tr: TeamResult = team_result  # type: ignore[assignment]

    for name, agent_result in zip(tr.agent_names, tr.agent_results, strict=True):
        status = "[green]OK[/green]" if agent_result.success else "[red]FAIL[/red]"
        console.print(
            f"  {status} {name}  "
            f"{agent_result.tokens_in}in/{agent_result.tokens_out}out  "
            f"{agent_result.duration_ms}ms"
        )

    if tr.success and tr.final_output:
        subtitle = (
            f"tokens: {tr.total_tokens_in}in/{tr.total_tokens_out}out | {tr.total_duration_ms}ms"
        )
        console.print(
            Panel(
                Markdown(tr.final_output),
                title="Team Result",
                subtitle=subtitle,
                border_style="green",
            )
        )
    elif not tr.success:
        console.print(Panel(f"[red]{tr.error}[/red]", title="Team Error", border_style="red"))


def _run_team(
    team_file: Path,
    prompt: str | None,
    dry_run: bool,
    audit_db: Path | None,
    no_audit: bool,
    report: Path | None,
    report_template: str,
) -> None:
    """Run a team YAML file."""
    if not prompt:
        console.print("[red]Error:[/red] Team mode requires --prompt (-p).")
        raise typer.Exit(1)

    from initrunner.cli._helpers import create_audit_logger
    from initrunner.team.loader import TeamLoadError, load_team
    from initrunner.team.runner import _team_report_role, run_team_dispatch

    try:
        team = load_team(team_file)
    except TeamLoadError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1) from None

    audit_logger = create_audit_logger(audit_db, no_audit)

    dry_run_model = None
    if dry_run:
        from pydantic_ai.models.test import TestModel

        dry_run_model = TestModel(custom_output_text="[dry-run] Simulated response.", call_tools=[])

    persona_names = list(team.spec.personas.keys())
    console.print(f"[bold]Team mode[/bold] -- team: [cyan]{team.metadata.name}[/cyan]")
    console.print(f"  Strategy: {team.spec.strategy}")
    console.print(f"  Personas: {', '.join(persona_names)}")
    if team.spec.shared_memory.enabled:
        console.print("  Shared memory: enabled")
    if team.spec.shared_documents.enabled:
        n_sources = len(team.spec.shared_documents.sources)
        console.print(f"  Shared documents: enabled ({n_sources} sources)")
    console.print()

    strategy = team.spec.strategy
    status_text = (
        "[dim]Running team pipeline (parallel)...[/dim]"
        if strategy == "parallel"
        else "[dim]Running team pipeline...[/dim]"
    )
    with console.status(status_text) as status:
        result = run_team_dispatch(
            team,
            prompt,
            team_dir=team_file.parent,
            audit_logger=audit_logger,
            dry_run_model=dry_run_model,
            on_persona_start=lambda name: status.update(f"[dim]Running persona: {name}...[/dim]"),
        )

    _display_team_result(result)

    if report is not None and result.agent_results:
        # Synthesize a RunResult for report export
        from initrunner.agent.executor import RunResult as _RunResult

        synthetic = _RunResult(
            run_id=result.team_run_id,
            output=result.final_output,
            tokens_in=result.total_tokens_in,
            tokens_out=result.total_tokens_out,
            total_tokens=result.total_tokens,
            tool_calls=result.total_tool_calls,
            duration_ms=result.total_duration_ms,
            success=result.success,
            error=result.error,
        )
        # Build a synthetic role for the report
        synthetic_role = _team_report_role(team)
        _maybe_export_report(
            synthetic_role,
            synthetic,
            prompt,
            report,
            report_template,
            dry_run,
        )

    if audit_logger is not None:
        audit_logger.close()

    if not result.success:
        raise typer.Exit(1)


def _display_suite_result(suite_result: object, verbose: bool = False) -> None:
    from initrunner.eval.runner import SuiteResult

    sr: SuiteResult = suite_result  # type: ignore[assignment]

    table = Table(title=f"Test Suite: {sr.suite_name}")
    table.add_column("Case", style="cyan")
    table.add_column("Status")
    table.add_column("Duration")
    table.add_column("Tokens", justify="right")
    if verbose:
        table.add_column("Details")

    for cr in sr.case_results:
        status = "[green]PASS[/green]" if cr.passed else "[red]FAIL[/red]"
        duration = f"{cr.duration_ms}ms"
        tokens = str(cr.run_result.total_tokens)

        details = ""
        if verbose and cr.assertion_results:
            lines = []
            for ar in cr.assertion_results:
                icon = "[green]\u2713[/green]" if ar.passed else "[red]\u2717[/red]"
                lines.append(f"{icon} {ar.message}")
            if not cr.run_result.success:
                lines.append(f"[red]Error: {cr.run_result.error}[/red]")
            details = "\n".join(lines)

        if verbose:
            table.add_row(cr.case.name, status, duration, tokens, details)
        else:
            table.add_row(cr.case.name, status, duration, tokens)

    console.print(table)
    counts = f"[bold]{sr.passed}/{sr.total} passed[/bold]"
    stats = f"[dim]{sr.total_tokens} tokens | {sr.total_duration_ms}ms total[/dim]"
    if sr.all_passed:
        console.print(f"\n{counts} [green]\u2713 All tests passed[/green]  {stats}")
    else:
        console.print(f"\n{counts} [red]\u2717 Some tests failed[/red]  {stats}")


def test(
    role_file: Annotated[
        Path, typer.Argument(help="Agent directory, role YAML, or installed role name")
    ],
    suite: Annotated[Path, typer.Option("-s", "--suite", help="Path to test suite YAML")],
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Simulate with TestModel (no API calls)")
    ] = False,
    verbose: Annotated[
        bool, typer.Option("-v", "--verbose", help="Show assertion details")
    ] = False,
    concurrency: Annotated[
        int, typer.Option("-j", "--concurrency", help="Number of concurrent workers")
    ] = 1,
    output: Annotated[
        Path | None, typer.Option("-o", "--output", help="Save JSON results to file")
    ] = None,
    tag: Annotated[
        list[str] | None, typer.Option("--tag", help="Filter cases by tag (repeatable)")
    ] = None,
    model: ModelOption = None,
) -> None:
    """Run a test suite against an agent role."""
    role_file = resolve_role_path(role_file)

    from initrunner.eval.runner import SuiteLoadError, load_suite
    from initrunner.services.eval import run_suite_sync, save_result

    resolved_model = resolve_model_override(model)

    if dry_run:
        from pydantic_ai import Agent
        from pydantic_ai.models.test import TestModel

        role = load_role_or_exit(role_file)
        agent = Agent(TestModel())
    else:
        role, agent = load_and_build_or_exit(role_file, model_override=resolved_model)

    try:
        test_suite = load_suite(suite)
    except SuiteLoadError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1) from None

    console.print(
        f"Running [cyan]{test_suite.metadata.name}[/cyan] "
        f"({len(test_suite.cases)} cases) against [cyan]{role.metadata.name}[/cyan]"
        + (" [dim](dry-run)[/dim]" if dry_run else "")
        + (f" [dim](concurrency={concurrency})[/dim]" if concurrency > 1 else "")
    )

    suite_result = run_suite_sync(
        agent,
        role,
        test_suite,
        dry_run=dry_run,
        concurrency=concurrency,
        tag_filter=tag,
        role_file=role_file,
    )
    _display_suite_result(suite_result, verbose=verbose)

    if output is not None:
        save_result(suite_result, output)
        console.print(f"[green]Results saved:[/green] {output}")

    if not suite_result.all_passed:
        raise typer.Exit(1)


def ingest(
    role_file: Annotated[
        Path, typer.Argument(help="Agent directory, role YAML, or installed role name")
    ],
    force: Annotated[bool, typer.Option("--force", help="Force re-ingestion of all files")] = False,
) -> None:
    """Ingest documents defined in the role's ingest config."""
    from rich.progress import BarColumn, MofNCompleteColumn, Progress, TextColumn

    from initrunner.cli._helpers import resolve_role_path
    from initrunner.ingestion.pipeline import FileStatus, resolve_sources, run_ingest

    role_file = resolve_role_path(role_file)
    role = load_role_or_exit(role_file)

    from initrunner.agent.loader import _load_dotenv

    _load_dotenv(role_file.parent)

    if role.spec.ingest is None:
        console.print("[red]Error:[/red] No ingest config in role definition.")
        raise typer.Exit(1)

    files, urls = resolve_sources(role.spec.ingest.sources, base_dir=role_file.parent)
    total = len(files) + len(urls)

    console.print(
        f"Ingesting for [cyan]{role.metadata.name}[/cyan]... ({len(files)} files, {len(urls)} URLs)"
    )

    if total == 0:
        console.print("[yellow]No files or URLs matched source patterns.[/yellow]")
        return

    with Progress(
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Ingesting", total=total)

        def on_progress(path: Path, status: FileStatus) -> None:
            progress.update(task, advance=1, description=f"[{_status_color(status)}]{path.name}")

        resource_limits = role.spec.security.resources
        try:
            stats = run_ingest(
                role.spec.ingest,
                role.metadata.name,
                provider=role.spec.model.provider,
                base_dir=role_file.parent,
                force=force,
                progress_callback=on_progress,
                max_file_size_mb=resource_limits.max_file_size_mb,
                max_total_ingest_mb=resource_limits.max_total_ingest_mb,
            )
        except Exception as exc:
            from initrunner.stores.base import EmbeddingModelChangedError

            if not isinstance(exc, EmbeddingModelChangedError):
                raise
            progress.stop()
            if typer.confirm(
                f"{exc} This requires wiping the store and re-ingesting all documents. Proceed?"
            ):
                progress.start()
                stats = run_ingest(
                    role.spec.ingest,
                    role.metadata.name,
                    provider=role.spec.model.provider,
                    base_dir=role_file.parent,
                    force=True,
                    progress_callback=on_progress,
                    max_file_size_mb=resource_limits.max_file_size_mb,
                    max_total_ingest_mb=resource_limits.max_total_ingest_mb,
                )
            else:
                console.print("[yellow]Aborted.[/yellow]")
                raise typer.Exit(1) from None

    parts = []
    if stats.new:
        parts.append(f"[green]New: {stats.new}[/green]")
    if stats.updated:
        parts.append(f"[yellow]Updated: {stats.updated}[/yellow]")
    if stats.skipped:
        parts.append(f"[dim]Skipped: {stats.skipped}[/dim]")
    if stats.errored:
        parts.append(f"[red]Errors: {stats.errored}[/red]")

    console.print(f"[green]Done.[/green] {stats.total_chunks} chunks stored. " + " | ".join(parts))

    for fr in stats.file_results:
        if fr.status == FileStatus.ERROR:
            console.print(f"  [red]Error:[/red] {fr.path}: {fr.error}")


def _status_color(status: object) -> str:
    from initrunner.ingestion.pipeline import FileStatus

    return {
        FileStatus.NEW: "green",
        FileStatus.UPDATED: "yellow",
        FileStatus.SKIPPED: "dim",
        FileStatus.ERROR: "red",
    }.get(status, "white")
