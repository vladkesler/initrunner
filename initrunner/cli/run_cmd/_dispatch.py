"""Mode-specific dispatch helpers for flow, serve, daemon, and bot."""

from __future__ import annotations

from pathlib import Path

import typer

from initrunner.cli._helpers import (
    command_context,
    console,
    create_audit_logger,
    resolve_model_override,
    resolve_skill_dirs,
)


def _dispatch_flow(flow_file: Path, audit_db: Path | None, no_audit: bool) -> None:
    """Run a flow file (foreground)."""
    from initrunner.flow.loader import FlowLoadError
    from initrunner.runner.display import _make_prefixed_tool_event_printer
    from initrunner.services.flow import load_flow_sync, run_flow_sync

    try:
        flow = load_flow_sync(flow_file)
    except FlowLoadError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1) from None

    audit_logger = create_audit_logger(audit_db, no_audit)

    try:
        run_flow_sync(
            flow,
            flow_file.parent,
            audit_logger=audit_logger,
            on_tool_event=_make_prefixed_tool_event_printer(),
        )
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
