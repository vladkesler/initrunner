"""Live ``(agent, role)`` holder with a locked atomic swap for the REPL.

Two REPL features rebuild the agent mid-session: hot-attaching a scaffolded
tool (:meth:`AgentHandle.rebuild_from_role`) and reloading an edited
``role.yaml`` (:meth:`AgentHandle.reload_from_disk`). PydanticAI cannot swap a
running agent's toolsets in place, so both rebuild a fresh ``Agent`` and swap
the live reference. Both funnel through one locked :meth:`AgentHandle._swap`,
mirroring :meth:`initrunner.runner.daemon.DaemonRunner._apply_reload`'s
atomic-swap + fail-open contract for the synchronous REPL.

The REPL keeps ``message_history`` as a plain list across the swap, so
conversation context survives a rebuild (PydanticAI message lists are
model-agnostic).
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pydantic_ai import Agent

    from initrunner.agent.schema.role import RoleDefinition

_logger = logging.getLogger(__name__)

# Runtime attributes set on the ``Agent`` object by callers, which ``build_agent``
# does not reconstruct: templating values (``--var``), the already-open memory
# store, and resume context. The loader's dynamic system-prompt closures read
# these off the agent (loader.py: ``_template_values`` at 791, ``_memory_store``
# at 804, ``_resume_context`` at 814), so a rebuild must carry them onto the new
# agent or templating, procedural memory, and resume would silently break.
_CARRYOVER_ATTRS: tuple[str, ...] = (
    "_template_values",
    "_memory_store",
    "_resume_context",
)


@dataclass(frozen=True, slots=True)
class ReloadResult:
    """Outcome of a rebuild, so the REPL can print a line without the handle
    touching the console."""

    ok: bool
    role: RoleDefinition | None
    agent: Agent | None
    error: str | None
    summary: str


class AgentHandle:
    """Mutable holder for the live ``(agent, role)`` pair plus rebuild inputs.

    Owns the locked atomic swap and the carry-over of externally-set agent
    attributes. Both A2 (``rebuild_from_role``) and the role-reload leg
    (``reload_from_disk``) build on it instead of reimplementing the swap.
    """

    def __init__(
        self,
        agent: Agent,
        role: RoleDefinition,
        *,
        role_dir: Path | None,
        role_path: Path | None = None,
        extra_skill_dirs: list[Path] | None = None,
        load_model_override: str | None = None,
    ) -> None:
        self._agent = agent
        self._role = role
        self._role_dir = role_dir
        self._role_path = role_path
        self._extra_skill_dirs = extra_skill_dirs
        self._load_model_override = load_model_override
        self._lock = threading.RLock()

    def current(self) -> tuple[Agent, RoleDefinition]:
        """Return the live ``(agent, role)`` pair under the lock."""
        with self._lock:
            return self._agent, self._role

    def rebuild_from_role(self, new_role: RoleDefinition) -> ReloadResult:
        """Rebuild the agent from an in-memory role (A2 tool hot-attach).

        Fail-open: on any build error the current agent/role are kept and an
        ``ok=False`` result is returned.
        """
        from initrunner.agent.loader import build_agent

        try:
            new_agent = build_agent(
                new_role,
                role_dir=self._role_dir,
                extra_skill_dirs=self._extra_skill_dirs,
            )
        except Exception as exc:
            _logger.warning("Agent rebuild failed; keeping current agent", exc_info=True)
            return ReloadResult(
                ok=False,
                role=None,
                agent=None,
                error=str(exc),
                summary="Rebuild failed; kept the current agent.",
            )
        self._swap(new_role, new_agent)
        return ReloadResult(
            ok=True,
            role=new_role,
            agent=new_agent,
            error=None,
            summary="Agent rebuilt.",
        )

    def reload_from_disk(self) -> ReloadResult:
        """Re-read ``role.yaml`` from disk and rebuild (role-reload leg).

        Returns a not-supported result when there is no backing file (an
        ephemeral, in-memory role). Fail-open on load/build errors.
        """
        if self._role_path is None:
            return ReloadResult(
                ok=False,
                role=None,
                agent=None,
                error=None,
                summary="No role file on disk to reload (ephemeral session).",
            )

        from initrunner.agent.loader import load_and_build

        try:
            new_role, new_agent = load_and_build(
                self._role_path,
                extra_skill_dirs=self._extra_skill_dirs,
                model_override=self._load_model_override,
            )
        except Exception as exc:
            _logger.warning("Role reload failed; keeping current config", exc_info=True)
            return ReloadResult(
                ok=False,
                role=None,
                agent=None,
                error=str(exc),
                summary="Reload failed; kept the current config.",
            )
        self._swap(new_role, new_agent)
        return ReloadResult(
            ok=True,
            role=new_role,
            agent=new_agent,
            error=None,
            summary=f"Reloaded {self._role_path.name}.",
        )

    def _swap(self, new_role: RoleDefinition, new_agent: Agent) -> None:
        """Atomically rebind ``(agent, role)``, carrying runtime agent attrs."""
        with self._lock:
            old_agent = self._agent
            for attr in _CARRYOVER_ATTRS:
                if hasattr(old_agent, attr):
                    try:
                        setattr(new_agent, attr, getattr(old_agent, attr))
                    except Exception:
                        _logger.debug("Could not carry over %s onto new agent", attr)
            self._agent = new_agent
            self._role = new_role
