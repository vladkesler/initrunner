"""Runner package: single-shot, interactive, autonomous, and daemon modes."""

from __future__ import annotations

from typing import TYPE_CHECKING

from initrunner.runner.autonomous import run_autonomous
from initrunner.runner.budget import DaemonTokenTracker
from initrunner.runner.daemon import run_daemon
from initrunner.runner.interactive import run_interactive
from initrunner.runner.single import run_single

if TYPE_CHECKING:
    from initrunner.agent.schema import RoleDefinition
    from initrunner.stores.base import MemoryStoreBase

__all__ = [
    "DaemonTokenTracker",
    "maybe_prune_sessions",
    "run_autonomous",
    "run_daemon",
    "run_interactive",
    "run_single",
]


def maybe_prune_sessions(
    role: RoleDefinition,
    memory_store: MemoryStoreBase | None,
) -> None:
    """Prune old memory sessions if memory is configured."""
    if memory_store is not None and role.spec.memory is not None:
        memory_store.prune_sessions(role.metadata.name, role.spec.memory.max_sessions)
