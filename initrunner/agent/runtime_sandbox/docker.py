"""DockerBackend -- container-based isolation via Docker."""

from __future__ import annotations

import subprocess
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from initrunner.agent._subprocess import SubprocessTimeout
from initrunner.agent.docker_sandbox import (
    _build_docker_cmd,
    _format_oom_hint,
    _generate_container_name,
    _kill_container,
    check_docker_available,
    ensure_image_available,
)
from initrunner.agent.runtime_sandbox.base import (
    SandboxResult,
    SandboxUnavailableError,
)
from initrunner.agent.schema.security import BindMount, SandboxConfig

if TYPE_CHECKING:
    from initrunner.audit.logger import AuditLogger
    from initrunner.audit.null import NullAuditLogger


class DockerBackend:
    """Run tool commands inside Docker containers."""

    def __init__(
        self,
        config: SandboxConfig,
        *,
        role_dir: Path | None = None,
        audit: AuditLogger | NullAuditLogger | None = None,
        agent_name: str = "",
    ) -> None:
        self._config = config
        self._role_dir = role_dir
        self._agent_name = agent_name
        from initrunner.audit.null import NullAuditLogger as _Null

        self._audit: AuditLogger | _Null = audit or _Null()

    @property
    def name(self) -> str:
        return "docker"

    def preflight(self) -> None:
        if not check_docker_available():
            raise SandboxUnavailableError(
                backend="docker",
                reason="Docker CLI not found or daemon not running",
                remediation=(
                    "Install Docker and start the daemon:\n"
                    "  Debian/Ubuntu: apt install docker.io && systemctl start docker\n"
                    "  macOS: brew install --cask docker (then open Docker Desktop)\n"
                    "  Fedora: dnf install docker && systemctl start docker"
                ),
            )
        ensure_image_available(self._config.docker.image)

    def run(
        self,
        argv: list[str],
        *,
        stdin: bytes | None = None,
        env: Mapping[str, str],
        cwd: Path,
        timeout: float,
        extra_mounts: Sequence[BindMount] = (),
        net: Literal["none", "bridge", "host"] = "none",
        memory_limit: str | None = None,
        cpu_limit: float | None = None,
    ) -> SandboxResult:
        name = _generate_container_name()

        mount_tuples = [(m.source, m.target, m.read_only) for m in extra_mounts]

        cmd = _build_docker_cmd(
            self._config,
            container_name=name,
            work_dir=str(cwd),
            extra_mounts=mount_tuples or None,
            interactive=stdin is not None,
            role_dir=self._role_dir,
            env=dict(env),
        )
        cmd.extend(argv)

        t0 = time.monotonic()
        try:
            result = subprocess.run(
                cmd,
                input=stdin,
                capture_output=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            _kill_container(name)
            raise SubprocessTimeout(int(timeout)) from None

        elapsed = (time.monotonic() - t0) * 1000
        stdout = result.stdout.decode("utf-8", errors="replace")
        stderr = _format_oom_hint(
            result.returncode,
            result.stderr.decode("utf-8", errors="replace"),
            self._config.memory_limit,
        )

        self._audit.log_security_event(
            "sandbox.exec",
            agent_name=self._agent_name,
            details=(
                f"backend=docker argv0={argv[0] if argv else ''} "
                f"rc={result.returncode} duration_ms={elapsed:.0f}"
            ),
        )

        return SandboxResult(
            stdout=stdout,
            stderr=stderr,
            returncode=result.returncode,
            duration_ms=elapsed,
        )

    async def arun(
        self,
        argv: list[str],
        *,
        stdin: bytes | None = None,
        env: Mapping[str, str],
        cwd: Path,
        timeout: float,
        extra_mounts: Sequence[BindMount] = (),
        net: Literal["none", "bridge", "host"] = "none",
        memory_limit: str | None = None,
        cpu_limit: float | None = None,
    ) -> SandboxResult:
        import anyio

        return await anyio.to_thread.run_sync(  # type: ignore[unresolved-attribute]
            lambda: self.run(
                argv,
                stdin=stdin,
                env=env,
                cwd=cwd,
                timeout=timeout,
                extra_mounts=extra_mounts,
                net=net,
                memory_limit=memory_limit,
                cpu_limit=cpu_limit,
            )
        )
