"""DockerBackend -- container-based isolation via Docker."""

from __future__ import annotations

import json
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

_RUNTIME_INSTALL_HINTS: dict[str, str] = {
    "runsc": (
        "gVisor (runsc): install per https://gvisor.dev/docs/user_guide/install/, "
        "register with Docker via /etc/docker/daemon.json, then restart the daemon."
    ),
    "kata-runtime": (
        "Kata Containers: install per https://github.com/kata-containers/kata-containers/"
        "blob/main/docs/install/README.md and register with Docker."
    ),
    "kata-qemu": "Kata Containers (QEMU hypervisor): install per the Kata install docs.",
    "kata-fc": "Kata Containers (Firecracker hypervisor): install per the Kata install docs.",
    "kata-clh": "Kata Containers (Cloud Hypervisor): install per the Kata install docs.",
    "runc": "runc ships with Docker by default; an unregistered runc points to a broken install.",
}


def _list_registered_runtimes() -> list[str] | None:
    """Return Docker's registered runtime names, or None if the query failed.

    None means we couldn't determine the runtime list (transient docker info
    failure, malformed JSON). Callers must treat that as "unknown" rather than
    "empty list," so a transient hiccup never silently passes preflight.
    """
    try:
        proc = subprocess.run(
            ["docker", "info", "--format", "{{json .Runtimes}}"],
            capture_output=True,
            timeout=5,
            check=False,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None
    if proc.returncode != 0:
        return None
    try:
        data = json.loads(proc.stdout.decode("utf-8", errors="replace"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    return [k for k in data.keys() if isinstance(k, str)]


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
        runtime = self._config.docker.runtime
        if runtime is not None:
            registered = _list_registered_runtimes()
            if registered is None:
                raise SandboxUnavailableError(
                    backend="docker",
                    reason=(
                        f"could not query Docker runtimes to verify '{runtime}' "
                        "(docker info failed or returned malformed output)"
                    ),
                    remediation=(
                        "Re-run after the Docker daemon stabilizes, or unset "
                        "security.sandbox.docker.runtime to fall back to the default."
                    ),
                )
            if runtime not in registered:
                hint = _RUNTIME_INSTALL_HINTS.get(
                    runtime, "Install the runtime and register it with Docker."
                )
                listed = ", ".join(sorted(registered)) or "(none)"
                raise SandboxUnavailableError(
                    backend="docker",
                    reason=(
                        f"runtime '{runtime}' is not registered with Docker. "
                        f"Registered runtimes: {listed}"
                    ),
                    remediation=hint,
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
