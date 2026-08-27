"""Running a whole group in one process: serve and daemon."""

from __future__ import annotations

from contextlib import ExitStack, contextmanager
from pathlib import Path
from typing import TYPE_CHECKING

import typer

from initrunner.cli._helpers import (
    console,
    create_audit_logger,
    print_error,
    resolve_model_override,
    resolve_skill_dirs,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from initrunner.audit.logger import AuditLogger
    from initrunner.group.prepare import PreparedMember
    from initrunner.group.schema import Roster
    from initrunner.sinks.dispatcher import SinkDispatcher
    from initrunner.stores.base import MemoryStoreBase

    GroupRuntime = tuple[
        Roster,
        dict[str, PreparedMember],
        AuditLogger | None,
        dict[str, MemoryStoreBase],
        dict[str, SinkDispatcher],
    ]


@contextmanager
def group_context(
    group_file: Path,
    *,
    no_audit: bool,
    with_memory: bool = False,
    with_sinks: bool = False,
    model: str | None = None,
) -> Iterator[GroupRuntime]:
    """Build every member of a group and own their resources for the process.

    The single-agent equivalent is ``command_context``; this is the same
    lifecycle (audit, tracing, memory stores, sinks) applied to each member,
    with preparation kept atomic so a service never comes up missing an agent.
    """
    from initrunner.cli.run_cmd._group import load_roster_or_exit
    from initrunner.group.prepare import GroupPrepareError, prepare_group
    from initrunner.observability import setup_tracing, shutdown_tracing
    from initrunner.sinks.dispatcher import SinkDispatcher
    from initrunner.stores.factory import managed_memory_store

    roster = load_roster_or_exit(group_file)
    audit_logger = create_audit_logger(None, no_audit)

    provider = None
    if roster.group.observability is not None:
        provider = setup_tracing(roster.group.observability, roster.group.name)

    try:
        prepared = prepare_group(
            roster,
            extra_skill_dirs=resolve_skill_dirs(None),
            model_override=resolve_model_override(model),
        )
    except GroupPrepareError as e:
        print_error(e)
        if audit_logger is not None:
            audit_logger.close()
        if provider is not None:
            shutdown_tracing()
        raise typer.Exit(1) from e

    memory_stores: dict[str, MemoryStoreBase] = {}
    sinks: dict[str, SinkDispatcher] = {}
    try:
        with ExitStack() as stack:
            for key, member in prepared.items():
                if with_memory:
                    store = stack.enter_context(managed_memory_store(member.role, member.agent))
                    if store is not None:
                        memory_stores[key] = store
                if with_sinks and member.role.spec.sinks:
                    sinks[key] = SinkDispatcher(
                        member.role.spec.sinks, member.role, role_dir=member.role_dir
                    )
            yield roster, prepared, audit_logger, memory_stores, sinks
    finally:
        if audit_logger is not None:
            audit_logger.close()
        if provider is not None:
            shutdown_tracing()


def dispatch_group_serve(
    group_file: Path,
    host: str | None,
    port: int | None,
    no_audit: bool,
    model: str | None,
) -> None:
    """Serve every member of a group from one OpenAI-compatible API."""
    import os

    from initrunner.middleware import resolve_exposed_api_key
    from initrunner.server.app import ServedMember, run_multi_server

    host = host or "127.0.0.1"
    port = port or 8000

    # Fail closed: never serve agents off-host without authentication.
    resolved_key, generated_key = resolve_exposed_api_key(
        host, os.environ.get("INITRUNNER_API_KEY")
    )
    with group_context(
        group_file,
        no_audit=no_audit,
        model=model,
    ) as (roster, prepared, audit_logger, _stores, _sinks):
        members = {
            key: ServedMember(key=key, role=member.role, agent=member.agent, role_path=member.path)
            for key, member in prepared.items()
        }
        console.print(f"Serving group [cyan]{roster.name}[/cyan] at http://{host}:{port}")
        for key, member in prepared.items():
            # A directory group keys on the role's own name, so the parenthetical
            # would just repeat it.
            name = member.role.metadata.name
            suffix = "" if name == key else f" [dim]({name})[/dim]"
            console.print(f"  Model ID: {key}{suffix}")
        console.print(f"  Health:   http://{host}:{port}/health")
        console.print(f"  Models:   http://{host}:{port}/v1/models")
        if generated_key is not None:
            console.print(
                "  Auth:     [yellow]enabled[/yellow] -- generated key"
                " (INITRUNNER_API_KEY not set):\n"
                f"            [bold]{generated_key}[/bold]"
            )
        elif resolved_key:
            console.print("  Auth:     [yellow]enabled[/yellow] (Bearer token required)")

        run_multi_server(
            members,
            security=roster.group.security,
            host=host,
            port=port,
            audit_logger=audit_logger,
            api_key=resolved_key,
        )


def dispatch_group_daemon(
    group_file: Path,
    no_audit: bool,
    model: str | None,
) -> None:
    """Run every trigger-driven member of a group in one process."""
    from initrunner.group.daemon import run_group_daemon

    with group_context(
        group_file,
        no_audit=no_audit,
        with_memory=True,
        with_sinks=True,
        model=model,
    ) as (roster, prepared, audit_logger, memory_stores, sinks):
        run_group_daemon(
            roster,
            prepared,
            audit_logger=audit_logger,
            memory_stores=memory_stores,
            sink_dispatchers=sinks,
            extra_skill_dirs=resolve_skill_dirs(None),
        )
