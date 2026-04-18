"""Resolve a SandboxConfig into a concrete SandboxBackend."""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from initrunner.agent.runtime_sandbox.base import SandboxUnavailableError
from initrunner.agent.runtime_sandbox.null import NullBackend
from initrunner.agent.schema.security import SandboxConfig

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from initrunner.agent.runtime_sandbox.base import SandboxBackend
    from initrunner.audit.logger import AuditLogger
    from initrunner.audit.null import NullAuditLogger


def resolve_backend(
    config: SandboxConfig,
    *,
    role_dir: Path | None = None,
    audit: AuditLogger | NullAuditLogger | None = None,
    agent_name: str = "",
) -> SandboxBackend:
    """Return a concrete backend for the given config. Never silently falls to null."""
    if audit is None:
        from initrunner.agent.runtime_sandbox import get_default_audit_logger

        audit = get_default_audit_logger()
    backend = config.backend

    if backend == "none":
        return NullBackend()

    if backend == "bwrap":
        from initrunner.agent.runtime_sandbox.bwrap import BwrapBackend

        return BwrapBackend(config, role_dir=role_dir, audit=audit, agent_name=agent_name)

    if backend == "docker":
        from initrunner.agent.runtime_sandbox.docker import DockerBackend

        return DockerBackend(config, role_dir=role_dir, audit=audit, agent_name=agent_name)

    if backend == "auto":
        return _resolve_auto(config, role_dir=role_dir, audit=audit, agent_name=agent_name)

    raise SandboxUnavailableError(
        backend=backend,
        reason=f"Unknown sandbox backend '{backend}'",
        remediation="Use one of: auto, bwrap, docker, none",
    )


def _resolve_auto(
    config: SandboxConfig,
    *,
    role_dir: Path | None = None,
    audit: AuditLogger | NullAuditLogger | None = None,
    agent_name: str = "",
) -> SandboxBackend:
    """auto: prefer bwrap on Linux, then docker, then error."""
    if sys.platform == "linux":
        from initrunner.agent.runtime_sandbox.bwrap import BwrapBackend

        bwrap = BwrapBackend(config, role_dir=role_dir, audit=audit, agent_name=agent_name)
        try:
            bwrap.preflight()
            return bwrap
        except SandboxUnavailableError as exc:
            logger.info(
                "sandbox backend 'auto': bwrap unavailable (%s); trying docker",
                exc.reason,
            )

    from initrunner.agent.runtime_sandbox.docker import DockerBackend

    docker = DockerBackend(config, role_dir=role_dir, audit=audit, agent_name=agent_name)
    try:
        docker.preflight()
        return docker
    except SandboxUnavailableError:
        pass

    raise SandboxUnavailableError(
        backend="auto",
        reason="No sandbox backend available on this host",
        remediation=(
            "Install at least one:\n"
            "  Linux: apt install bubblewrap\n"
            "  Any platform: install Docker and start the daemon"
        ),
    )
