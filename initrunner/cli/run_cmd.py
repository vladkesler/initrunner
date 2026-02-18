"""Run commands: run, test, ingest, daemon."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.table import Table

from initrunner.cli._helpers import (
    command_context,
    console,
    load_and_build_or_exit,
    load_role_or_exit,
    resolve_skill_dirs,
)


def _maybe_export_report(
    role: object,
    result: object,
    prompt: object,
    output_path: Path,
    template_name: str,
    dry_run: bool,
) -> None:
    """Try to export a report; warn on failure, never crash."""
    try:
        from initrunner.agent.prompt import extract_text_from_prompt
        from initrunner.report import export_report

        prompt_text = extract_text_from_prompt(prompt)
        path = export_report(
            role, result, prompt_text, output_path, template_name=template_name, dry_run=dry_run
        )
        console.print(f"[green]Report exported:[/green] {path}")
    except Exception as e:
        console.print(f"[yellow]Warning:[/yellow] Report export failed: {e}")


def run(
    role_file: Annotated[Path, typer.Argument(help="Path to role.yaml")],
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
    audit_db: Annotated[Path | None, typer.Option(help="Path to audit database")] = None,
    no_audit: Annotated[bool, typer.Option(help="Disable audit logging")] = False,
    skill_dir: Annotated[
        Path | None, typer.Option("--skill-dir", help="Extra skill search directory")
    ] = None,
    attach: Annotated[
        list[str] | None,
        typer.Option(
            "--attach",
            "-A",
            help="Attach file or URL (repeatable, supports images/audio/video/docs)",
        ),
    ] = None,
    export_report: Annotated[
        bool, typer.Option("--export-report", help="Export markdown report after run")
    ] = False,
    report_path: Annotated[
        Path,
        typer.Option("--report-path", help="Report output path (default: ./initrunner-report.md)"),
    ] = Path("initrunner-report.md"),
    report_template: Annotated[
        str,
        typer.Option(
            "--report-template",
            help="Report template: default, pr-review, changelog, ci-fix",
        ),
    ] = "default",
) -> None:
    """Run an agent with a role definition."""
    if autonomous and not prompt:
        console.print("[red]Error:[/red] --autonomous requires --prompt (-p).")
        raise typer.Exit(1)
    if autonomous and interactive:
        console.print("[red]Error:[/red] --autonomous and --interactive are mutually exclusive.")
        raise typer.Exit(1)

    if export_report:
        from initrunner.report import BUILT_IN_TEMPLATES

        if report_template not in BUILT_IN_TEMPLATES:
            console.print(
                f"[red]Error:[/red] Unknown template '{report_template}'. "
                f"Available: {', '.join(BUILT_IN_TEMPLATES)}"
            )
            raise typer.Exit(1)

    import sys

    if attach and not prompt and not interactive and sys.stdin.isatty():
        console.print("[red]Error:[/red] use --prompt with --attach or pipe stdin.")
        raise typer.Exit(1)

    from initrunner.runner import run_autonomous, run_interactive, run_single

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

    with command_context(
        role_file,
        audit_db=audit_db,
        no_audit=no_audit,
        with_memory=True,
        with_sinks=True,
        extra_skill_dirs=resolve_skill_dirs(skill_dir),
    ) as (role, agent, audit_logger, memory_store, sink_dispatcher):
        message_history = None
        run_result = None  # RunResult or AutonomousResult

        if autonomous:
            assert user_prompt is not None  # guarded above
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
            run_result, _ = run_single(
                agent,
                role,
                user_prompt,
                audit_logger=audit_logger,
                sink_dispatcher=sink_dispatcher,
                model_override=model_override,
            )
        elif user_prompt and interactive:
            run_result, message_history = run_single(
                agent,
                role,
                user_prompt,
                audit_logger=audit_logger,
                sink_dispatcher=sink_dispatcher,
                model_override=model_override,
            )
            if export_report:
                _maybe_export_report(
                    role, run_result, user_prompt, report_path, report_template, dry_run
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
            )

        # Export for non-interactive branches (after run completes)
        if export_report and run_result is not None and not (user_prompt and interactive):
            _maybe_export_report(
                role, run_result, user_prompt, report_path, report_template, dry_run
            )


def _display_suite_result(suite_result: object, verbose: bool = False) -> None:
    from initrunner.eval.runner import SuiteResult

    sr: SuiteResult = suite_result  # type: ignore[assignment]

    table = Table(title=f"Test Suite: {sr.suite_name}")
    table.add_column("Case", style="cyan")
    table.add_column("Status")
    table.add_column("Duration")
    if verbose:
        table.add_column("Details")

    for cr in sr.case_results:
        status = "[green]PASS[/green]" if cr.passed else "[red]FAIL[/red]"
        duration = f"{cr.duration_ms}ms"

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
            table.add_row(cr.case.name, status, duration, details)
        else:
            table.add_row(cr.case.name, status, duration)

    console.print(table)
    counts = f"[bold]{sr.passed}/{sr.total} passed[/bold]"
    if sr.all_passed:
        console.print(f"\n{counts} [green]\u2713 All tests passed[/green]")
    else:
        console.print(f"\n{counts} [red]\u2717 Some tests failed[/red]")


def test(
    role_file: Annotated[Path, typer.Argument(help="Path to role.yaml")],
    suite: Annotated[Path, typer.Option("-s", "--suite", help="Path to test suite YAML")],
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Simulate with TestModel (no API calls)")
    ] = False,
    verbose: Annotated[
        bool, typer.Option("-v", "--verbose", help="Show assertion details")
    ] = False,
) -> None:
    """Run a test suite against an agent role."""
    from initrunner.eval.runner import SuiteLoadError, load_suite, run_suite

    role, agent = load_and_build_or_exit(role_file)

    try:
        test_suite = load_suite(suite)
    except SuiteLoadError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1) from None

    console.print(
        f"Running [cyan]{test_suite.metadata.name}[/cyan] "
        f"({len(test_suite.cases)} cases) against [cyan]{role.metadata.name}[/cyan]"
        + (" [dim](dry-run)[/dim]" if dry_run else "")
    )

    suite_result = run_suite(agent, role, test_suite, dry_run=dry_run)
    _display_suite_result(suite_result, verbose=verbose)

    if not suite_result.all_passed:
        raise typer.Exit(1)


def ingest(
    role_file: Annotated[Path, typer.Argument(help="Path to role.yaml")],
    force: Annotated[bool, typer.Option("--force", help="Force re-ingestion of all files")] = False,
) -> None:
    """Ingest documents defined in the role's ingest config."""
    from rich.progress import BarColumn, MofNCompleteColumn, Progress, TextColumn

    from initrunner.ingestion.pipeline import FileStatus, resolve_sources, run_ingest

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
            from initrunner.stores.sqlite_vec import EmbeddingModelChangedError

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


def daemon(
    role_file: Annotated[Path, typer.Argument(help="Path to role.yaml")],
    audit_db: Annotated[Path | None, typer.Option(help="Path to audit database")] = None,
    no_audit: Annotated[bool, typer.Option(help="Disable audit logging")] = False,
    skill_dir: Annotated[
        Path | None, typer.Option("--skill-dir", help="Extra skill search directory")
    ] = None,
) -> None:
    """Run agent in daemon mode with triggers."""
    from initrunner.runner import run_daemon

    with command_context(
        role_file,
        audit_db=audit_db,
        no_audit=no_audit,
        with_memory=True,
        with_sinks=True,
        extra_skill_dirs=resolve_skill_dirs(skill_dir),
    ) as (role, agent, audit_logger, memory_store, sink_dispatcher):
        run_daemon(
            agent,
            role,
            audit_logger=audit_logger,
            sink_dispatcher=sink_dispatcher,
            memory_store=memory_store,
        )
