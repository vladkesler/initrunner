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
from initrunner.cli._options import ModelOption, NoAuditOption
from initrunner.cli._run_agent import _run_agent
from initrunner.cli._run_team import _run_team
from initrunner.cli.run_cmd._dispatch import (
    _dispatch_daemon,
    _dispatch_flow,
    _dispatch_serve,
)
from initrunner.cli.run_cmd._sensing import _resolve_via_sensing
from initrunner.cli.run_cmd._starters import _show_starter_listing
from initrunner.cli.run_cmd._validate import (
    EPHEMERAL_KIND,
    RunMode,
    _resolve_run_mode,
    _validate_kind_flags,
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
    resume: Annotated[bool, typer.Option("--resume", help="Resume previous REPL session")] = False,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Simulate with TestModel (no API calls)")
    ] = False,
    no_audit: NoAuditOption = False,
    attach: Annotated[
        list[str] | None,
        typer.Option(
            "--attach",
            "-A",
            help="Attach file or URL (repeatable, supports images/audio/video/docs)",
        ),
    ] = None,
    report: Annotated[
        str | None,
        typer.Option(
            "--report",
            help="Export a markdown report to PATH, or TEMPLATE:PATH to pick a template"
            " (default, pr-review, changelog, ci-fix)",
        ),
    ] = None,
    output_format: Annotated[
        str,
        typer.Option("-f", "--format", help="Output format: auto, json, text, rich"),
    ] = "auto",
    agent_member: Annotated[
        str | None,
        typer.Option("--agent", help="Which agent to run, for a group of agents"),
    ] = None,
    sense: Annotated[
        bool, typer.Option("--sense", help="Sense the best role for the given prompt")
    ] = False,
    model: ModelOption = None,
    # --- Mode flags ---
    daemon_mode: Annotated[
        bool, typer.Option("--daemon", help="Run in daemon mode with triggers")
    ] = False,
    serve_mode: Annotated[
        bool, typer.Option("--serve", help="Serve as OpenAI-compatible API")
    ] = False,
    # --- Serve options ---
    # Deployment inputs, not agent behaviour: the same role binds to loopback on
    # a laptop and to 0.0.0.0 in a container. Default None so "not given" is
    # distinguishable from the value.
    host: Annotated[
        str | None,
        typer.Option(help="Host to bind to (default: 127.0.0.1)", rich_help_panel="Serve Options"),
    ] = None,
    port: Annotated[
        int | None,
        typer.Option(help="Port to listen on (default: 8000)", rich_help_panel="Serve Options"),
    ] = None,
    # --- Ephemeral mode options ---
    tools: Annotated[
        list[str] | None,
        typer.Option(
            "--tools",
            help="Tools for ephemeral mode: a profile (none, minimal, all) and/or tool types"
            " (datetime, web_reader, search, python, filesystem, git, shell, slack)."
            " Repeatable or comma-separated. Default: minimal.",
            rich_help_panel="Ephemeral Mode",
        ),
    ] = None,
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
    template_vars: Annotated[
        list[str] | None,
        typer.Option(
            "--var",
            help="Template variable (KEY=VALUE, repeatable) for {{var}} placeholders in spec.role",
        ),
    ] = None,
) -> None:
    """Run an agent from a YAML file, starter name, or ephemeral mode.

    Without a role file, starts an ephemeral REPL with auto-detected provider.
    Use --list to see available starter agents.
    """
    # --- --list: show starters ---
    if list_starters:
        _show_starter_listing()
        raise typer.Exit(0)

    # --- Universal validation (before ephemeral / role branching) ---
    mode = _resolve_run_mode(
        daemon_mode=daemon_mode,
        serve_mode=serve_mode,
        autonomous=autonomous,
    )
    # Every flag whose support depends on the run mode or on what is being run.
    # Built once and checked against both, so nothing is accepted then ignored.
    active_flags = {
        "--interactive": interactive,
        "--autonomous": autonomous,
        "--resume": resume,
        "--attach": bool(attach),
        "--report": report is not None,
        "--var": bool(template_vars),
        "--format": output_format != "auto",
        "--dry-run": dry_run,
        "--model": model is not None,
        "--agent": agent_member is not None,
    }

    _validate_universal_flags(
        mode=mode,
        output_format=output_format,
        sense=sense,
        prompt=prompt,
        host=host,
        port=port,
        active_flags=active_flags,
    )

    # --- No role file + no --sense: ephemeral mode ---
    if role_file is None and not sense:
        _validate_kind_flags(EPHEMERAL_KIND, mode, active_flags=active_flags)
        # --resume only valid for a REPL (no -p, or -p with -i)
        if resume and prompt and not interactive:
            console.print("[red]Error:[/red] --resume requires -i when used with -p.")
            raise typer.Exit(1)

        from initrunner.cli._ephemeral import dispatch_ephemeral

        dispatch_ephemeral(
            model=model,
            prompt=prompt,
            interactive=interactive,
            tools=tools,
            memory=memory,
            resume=resume,
            ingest=ingest,
            attach=attach,
            no_audit=no_audit,
        )
        return

    # --- Role-incompatible flags ---
    _validate_role_only_flags(tools=tools, memory=memory, ingest=ingest)

    # --- Report target: TEMPLATE:PATH or PATH ---
    report_spec = None
    if report is not None:
        from initrunner.report import parse_report_spec

        try:
            report_spec = parse_report_spec(report)
        except ValueError as e:
            console.print(f"[red]Error:[/red] {e}")
            raise typer.Exit(1) from None

    # --- Intent sensing over the roles on disk ---
    # With a target file, sensing instead picks among a group's members, which
    # needs the target's kind; that happens after resolution below.
    sense_over_members = sense and role_file is not None
    if sense and not sense_over_members:
        role_file = _resolve_via_sensing(
            prompt,  # type: ignore[arg-type]  # guarded by _validate_universal_flags
            dry_run=dry_run,
        )

    # --- Resolve target and detect kind ---
    if role_file is None:
        raise RuntimeError("role_file unresolved")

    resolved, kind = resolve_run_target(role_file)
    role_file = resolved
    # A directory of agents is a group whose target is the directory itself.
    # Everything below that reads one YAML document skips it; its members were
    # each loaded and validated by the group loader, atomically.
    from initrunner.services.migrate import envelope_warning_for

    if not role_file.is_dir():
        warning = envelope_warning_for(role_file)
        if warning:
            console.print(f"[yellow]Warning:[/yellow] {warning}")

    # --- Starter: prerequisites + model auto-detect ---
    from initrunner.cli._helpers import prepare_starter

    starter_model = None if role_file.is_dir() else prepare_starter(role_file, model)
    effective_model = starter_model or model

    # --- Removed kind rejection ---
    if kind == "Pipeline":
        console.print(
            "[red]Error:[/red] kind: Pipeline has been removed.\n"
            "Use Team for one-shot multi-agent workflows, or Flow for long-running agents."
        )
        raise typer.Exit(1)

    # --- Group targets: pick a member, or act on the group as a whole ---
    role_mutator = None
    if kind == "Group":
        from initrunner.cli.run_cmd._group import (
            load_roster_or_exit,
            member_overlay,
            print_members,
            resolve_member_or_exit,
            sense_member_or_exit,
        )

        roster = load_roster_or_exit(role_file)
        if sense_over_members:
            agent_member = sense_member_or_exit(
                roster,
                prompt,  # type: ignore[arg-type]  # guarded by _validate_universal_flags
                dry_run=dry_run,
            )
            active_flags["--agent"] = True

        if agent_member is not None:
            # A selected member runs through every normal single-agent path;
            # the overlay is what carries the group's shared stores into it.
            role_file = resolve_member_or_exit(roster, agent_member)
            role_mutator = member_overlay(roster)
            kind = "Agent"
    elif sense_over_members:
        console.print("[red]Error:[/red] --sense and a role_file are mutually exclusive.")
        raise typer.Exit(1)
    elif agent_member is not None:
        console.print(
            f"[red]Error:[/red] --agent picks one member of a group, and {role_file} is not"
            f" a group (kind: {kind})."
        )
        raise typer.Exit(1)

    # --- Kind-specific flag validation ---
    _validate_kind_flags(kind, mode, active_flags=active_flags)

    # A group has no single run of its own: name the agent you meant.
    if kind == "Group" and mode == RunMode.STANDARD:
        print_members(roster, role_file)
        raise typer.Exit(1)

    # --- Pre-flight YAML validation: catch syntax/schema errors before any
    #     skill resolution, model resolution, or API calls.  Covers all
    #     downstream dispatches (Agent/Team/Flow, serve/daemon).  Runs
    #     after the cheap flag checks above so flag errors fire first.
    if not role_file.is_dir():
        preflight_validate_or_exit(role_file)

    # --- Kind-based dispatch ---
    if kind == "Team":
        _run_team(role_file, prompt, dry_run, no_audit)
        return

    if kind == "Flow":
        _dispatch_flow(role_file, no_audit, prompt=prompt)
        return

    if kind == "Group":
        # Every member in one process. Narrowing to one member rewrote the kind
        # to Agent above, so only whole-group modes reach here.
        from initrunner.cli.run_cmd._group_dispatch import (
            dispatch_group_daemon,
            dispatch_group_serve,
        )

        if mode == RunMode.SERVE:
            dispatch_group_serve(role_file, host, port, no_audit, effective_model)
        else:
            dispatch_group_daemon(role_file, no_audit, effective_model)
        return

    # --- Agent mode: flag-based dispatch ---
    if mode == RunMode.SERVE:
        _dispatch_serve(
            role_file,
            host,
            port,
            no_audit,
            effective_model,
            role_mutator=role_mutator,
        )
        return

    if mode == RunMode.DAEMON:
        _dispatch_daemon(
            role_file,
            no_audit,
            effective_model,
            role_mutator=role_mutator,
        )
        return

    # --- Parse --var KEY=VALUE pairs into a dict ---
    template_values: dict[str, str] = {}
    for raw in template_vars or []:
        if "=" not in raw:
            console.print(f"[red]Error:[/red] --var must be KEY=VALUE, got {raw!r}")
            raise typer.Exit(1)
        key, _, value = raw.partition("=")
        template_values[key.strip()] = value

    # --- Standard agent execution ---
    _run_agent(
        role_file,
        prompt=prompt,
        interactive=interactive,
        autonomous=autonomous,
        resume=resume,
        dry_run=dry_run,
        no_audit=no_audit,
        attach=attach,
        report_spec=report_spec,
        output_format=output_format,
        model=effective_model,
        template_values=template_values or None,
        role_mutator=role_mutator,
    )
