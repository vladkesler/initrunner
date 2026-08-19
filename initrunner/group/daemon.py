"""Run a group's trigger-driven agents in one process.

Each member gets its own ``DaemonRunner`` -- its own triggers, budget, circuit
breaker and conversation history -- but they share one process, one stop event
and one set of signal handlers, because signal handlers only install on the
main thread.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import TYPE_CHECKING

from initrunner._log import get_logger
from initrunner.runner.display import console

if TYPE_CHECKING:
    from initrunner.audit.logger import AuditLogger
    from initrunner.group.prepare import PreparedMember
    from initrunner.group.schema import Roster
    from initrunner.sinks.dispatcher import SinkDispatcher
    from initrunner.stores.base import MemoryStoreBase

logger = get_logger("group.daemon")

_JOIN_TIMEOUT_SECONDS = 60


def run_group_daemon(
    roster: Roster,
    prepared: dict[str, PreparedMember],
    *,
    audit_logger: AuditLogger | None = None,
    memory_stores: dict[str, MemoryStoreBase] | None = None,
    sink_dispatchers: dict[str, SinkDispatcher] | None = None,
    extra_skill_dirs: list[Path] | None = None,
    autopilot: bool = False,
) -> None:
    """Start every member that has triggers and block until stopped."""
    from initrunner._signal import install_shutdown_handler
    from initrunner.runner.daemon import DaemonRunner

    memory_stores = memory_stores or {}
    sink_dispatchers = sink_dispatchers or {}

    triggered = {k: m for k, m in prepared.items() if m.role.spec.triggers}
    idle = [k for k in prepared if k not in triggered]
    if idle:
        console.print(
            f"[yellow]No triggers configured for: {', '.join(idle)}."
            " They are part of the group but will not run in daemon mode.[/yellow]"
        )
    if not triggered:
        console.print(
            f"[red]Error:[/red] no agent in group '{roster.name}' has triggers configured."
            " Daemon mode is trigger-driven; give at least one member 'triggers:'."
        )
        return

    stop = threading.Event()
    runners: dict[str, DaemonRunner] = {}
    for key, member in triggered.items():
        runners[key] = DaemonRunner(
            member.agent,
            member.role,
            audit_logger=audit_logger,
            sink_dispatcher=sink_dispatchers.get(key),
            memory_store=memory_stores.get(key),
            role_path=member.path,
            extra_skill_dirs=extra_skill_dirs,
            autopilot=autopilot,
            stop_event=stop,
            install_signal_handler=False,
            rebuild=_make_rebuild(roster, member, extra_skill_dirs),
            label=key,
        )

    console.print(
        f"\nGroup [cyan]{roster.name}[/cyan]: running {len(runners)} agent(s) "
        f"({', '.join(runners)})"
    )

    threads = [
        threading.Thread(target=runner.run, name=f"daemon-{key}", daemon=False)
        for key, runner in runners.items()
    ]
    for thread in threads:
        thread.start()

    def _on_first_signal() -> None:
        for runner in runners.values():
            runner._on_first_signal()

    install_shutdown_handler(stop, on_first_signal=_on_first_signal)

    try:
        while not stop.wait(timeout=30):
            if not any(t.is_alive() for t in threads):
                # Every member stopped on its own; nothing left to wait for.
                stop.set()
    finally:
        stop.set()
        for thread in threads:
            thread.join(timeout=_JOIN_TIMEOUT_SECONDS)
            if thread.is_alive():
                logger.warning("%s did not stop within the grace period", thread.name)

    console.print(f"Group {roster.name} stopped.")


def _make_rebuild(
    roster: Roster,
    member: PreparedMember,
    extra_skill_dirs: list[Path] | None,
):
    """Rebuild a member on hot reload, keeping the group's shared stores."""
    from initrunner.group.prepare import make_group_overlay

    overlay = make_group_overlay(roster.group)

    def rebuild(path: Path):
        from initrunner.agent.loader import load_and_build

        return load_and_build(
            path,
            extra_skill_dirs=extra_skill_dirs,
            role_mutator=overlay,
        )

    return rebuild
