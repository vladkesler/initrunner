"""Mode-specific dispatch helpers for flow, serve, daemon, and bot."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import typer

from initrunner.cli._helpers import (
    command_context,
    console,
    create_audit_logger,
    resolve_model_override,
    resolve_skill_dirs,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from initrunner.agent.schema.role import RoleDefinition

    # Applied to the role just before its agent is built. A group member passes
    # one in so it picks up the group's shared stores; solo runs pass nothing.
    RoleMutator = Callable[[RoleDefinition], RoleDefinition] | None


def _dispatch_flow(
    flow_file: Path,
    no_audit: bool,
    prompt: str | None = None,
) -> None:
    """Run a flow file. ``prompt`` does a one-shot graph run; otherwise daemon."""
    from initrunner.flow.loader import FlowLoadError
    from initrunner.runner.display import _make_prefixed_tool_event_printer
    from initrunner.services.flow import load_flow_sync, run_flow_once_sync, run_flow_sync

    try:
        flow = load_flow_sync(flow_file)
    except FlowLoadError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1) from None

    audit_logger = create_audit_logger(None, no_audit)

    try:
        if prompt:
            result = run_flow_once_sync(
                flow,
                flow_file.parent,
                prompt,
                audit_logger=audit_logger,
                on_tool_event=_make_prefixed_tool_event_printer(),
            )
            console.print(result.output or "[dim](no output)[/dim]")
        else:
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
    host: str | None,
    port: int | None,
    no_audit: bool,
    model: str | None,
    role_mutator: RoleMutator = None,
) -> None:
    """Serve an agent as an OpenAI-compatible API."""
    import os

    from initrunner.middleware import resolve_exposed_api_key
    from initrunner.server.app import run_server

    host = host or "127.0.0.1"
    port = port or 8000

    # Fail closed: the completions endpoint drives the agent, so don't serve it
    # off-host without auth. The key is environment-only; a key on the command
    # line shows up in ps.
    api_key, generated_key = resolve_exposed_api_key(host, os.environ.get("INITRUNNER_API_KEY"))
    resolved_model = resolve_model_override(model)
    with command_context(
        role_file,
        audit_db=None,
        no_audit=no_audit,
        extra_skill_dirs=resolve_skill_dirs(None),
        model_override=resolved_model,
        role_mutator=role_mutator,
    ) as (role, agent, audit_logger, _memory_store, _sink_dispatcher):
        console.print(f"Serving [cyan]{role.metadata.name}[/cyan] at http://{host}:{port}")
        console.print(f"  Model ID: {role.metadata.name}")
        console.print(f"  Health:   http://{host}:{port}/health")
        console.print(f"  Models:   http://{host}:{port}/v1/models")
        if generated_key is not None:
            console.print(
                "  Auth:     [yellow]enabled[/yellow] -- generated key"
                " (INITRUNNER_API_KEY not set):\n"
                f"            [bold]{generated_key}[/bold]"
            )
        elif api_key:
            console.print("  Auth:     [yellow]enabled[/yellow] (Bearer token required)")

        run_server(
            agent,
            role,
            host=host,
            port=port,
            audit_logger=audit_logger,
            api_key=api_key,
            role_path=role_file,
        )


def _dispatch_daemon(
    role_file: Path,
    no_audit: bool,
    model: str | None,
    *,
    role_mutator: RoleMutator = None,
) -> None:
    """Run agent in daemon mode with triggers."""
    from initrunner.runner import run_daemon

    resolved_model = resolve_model_override(model)
    extra_skill_dirs = resolve_skill_dirs(None)
    with command_context(
        role_file,
        audit_db=None,
        no_audit=no_audit,
        with_memory=True,
        with_sinks=True,
        extra_skill_dirs=extra_skill_dirs,
        model_override=resolved_model,
        role_mutator=role_mutator,
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
