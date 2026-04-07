"""Agent execution: single-shot, REPL, autonomous, and formatted output."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

import typer

from initrunner.cli._helpers import (
    command_context,
    console,
    resolve_model_override,
    resolve_skill_dirs,
    suggest_next,
)

if TYPE_CHECKING:
    from pydantic_ai import Agent
    from pydantic_ai.models import Model

    from initrunner.agent.executor import AutonomousResult, RunResult
    from initrunner.agent.prompt import UserPrompt
    from initrunner.agent.schema.role import RoleDefinition
    from initrunner.audit.logger import AuditLogger
    from initrunner.sinks.dispatcher import SinkDispatcher


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


def _resolve_output_format(
    output_format: str,
    *,
    no_stream: bool,
    autonomous: bool,
    output_type: str,
) -> str:
    """Resolve auto/json/text/rich/stream based on context."""
    if output_format in ("json", "text"):
        effective = output_format
    elif output_format == "rich":
        effective = "rich"
    else:  # auto
        if not sys.stdout.isatty():
            effective = "text"
        elif autonomous:
            effective = "rich"
        elif output_type != "text":
            effective = "rich"
        else:
            effective = "stream"

    if no_stream and effective == "stream":
        effective = "rich"

    return effective


def _build_user_prompt(
    prompt: str | None,
    attach: list[str] | None,
) -> str | UserPrompt | None:
    """Build multimodal prompt if attachments provided."""
    if attach and prompt:
        from initrunner.agent.prompt import build_multimodal_prompt

        try:
            return build_multimodal_prompt(prompt, attach)
        except (FileNotFoundError, ValueError) as e:
            console.print(f"[red]Attachment error:[/red] {e}")
            raise typer.Exit(1) from None
    return prompt


def _run_formatted(
    effective: str,
    agent: Agent,
    role: RoleDefinition,
    prompt: UserPrompt,
    *,
    audit_logger: AuditLogger | None = None,
    sink_dispatcher: SinkDispatcher | None = None,
    model_override: Model | str | None = None,
) -> tuple:
    """Execute a single prompt and display in plain-text or JSON format.

    Bypasses ``run_single`` to avoid Rich panel output.  Spinner goes to
    stderr so stdout remains clean for piping.
    """
    from rich.console import Console as _Console

    from initrunner.agent.prompt import extract_text_from_prompt
    from initrunner.runner.display import _display_result_json, _display_result_plain
    from initrunner.services.execution import execute_run_sync

    stderr_console = _Console(stderr=True)
    with stderr_console.status("Thinking...", spinner="dots"):
        result, messages = execute_run_sync(
            agent,
            role,
            prompt,
            audit_logger=audit_logger,
            model_override=model_override,
        )

    if effective == "json":
        _display_result_json(result)
    else:
        _display_result_plain(result)

    if sink_dispatcher is not None:
        sink_dispatcher.dispatch(result, extract_text_from_prompt(prompt))

    return result, messages


def _run_agent(
    role_file: Path,
    *,
    prompt: str | None,
    interactive: bool,
    autonomous: bool,
    max_iterations: int | None,
    resume: bool,
    dry_run: bool,
    audit_db: Path | None,
    no_audit: bool,
    skill_dir: Path | None,
    attach: list[str] | None,
    report: Path | None,
    report_template: str,
    output_format: str,
    no_stream: bool,
    model: str | None,
) -> None:
    """Standard agent execution: single-shot, REPL, or autonomous."""
    if autonomous and not prompt:
        console.print("[red]Error:[/red] --autonomous requires --prompt (-p).")
        raise typer.Exit(1)
    if autonomous and interactive:
        console.print("[red]Error:[/red] --autonomous and --interactive are mutually exclusive.")
        raise typer.Exit(1)

    if report_template != "default" and report is None:
        console.print("[red]Error:[/red] --report-template requires --report PATH.")
        raise typer.Exit(1)

    if report_template != "default":
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

    user_prompt = _build_user_prompt(prompt, attach)

    resolved_model = resolve_model_override(model)
    with command_context(
        role_file,
        audit_db=audit_db,
        no_audit=no_audit,
        with_memory=True,
        with_sinks=True,
        extra_skill_dirs=resolve_skill_dirs(skill_dir),
        model_override=resolved_model,
        dry_run=dry_run,
    ) as (role, agent, audit_logger, memory_store, sink_dispatcher):
        if not prompt and not autonomous and role.spec.triggers:
            console.print(
                "[dim]Hint: this role has triggers. Use --daemon to run in daemon mode.[/dim]"
            )

        effective = _resolve_output_format(
            output_format,
            no_stream=no_stream,
            autonomous=autonomous,
            output_type=role.spec.output.type,
        )
        use_stream = effective == "stream"
        _run_single = run_single_stream if use_stream else run_single

        run_result = None
        message_history = None

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
            if effective in ("text", "json"):
                run_result, _ = _run_formatted(
                    effective,
                    agent,
                    role,
                    user_prompt,
                    audit_logger=audit_logger,
                    sink_dispatcher=sink_dispatcher,
                    model_override=model_override,
                )
            else:
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
            suggest_next("run_repl_exit", role, role_file)
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
            suggest_next("run_repl_exit", role, role_file)

        # Export for non-interactive branches (after run completes)
        if report is not None and run_result is not None and not (user_prompt and interactive):
            _maybe_export_report(role, run_result, user_prompt, report, report_template, dry_run)

        # Suggest next steps for non-interactive rich/stream runs (after report export)
        if run_result is not None and effective not in ("text", "json") and not interactive:
            ctx = "run_autonomous" if autonomous else "run_single"
            suggest_next(ctx, role, role_file)
