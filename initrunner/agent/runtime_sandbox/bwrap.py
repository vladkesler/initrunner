"""BwrapBackend -- bubblewrap-based isolation for Linux."""

from __future__ import annotations

import logging
import shutil
import subprocess
import sys
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from initrunner.agent._subprocess import SubprocessTimeout, scrub_env
from initrunner.agent.runtime_sandbox.base import (
    SandboxConfigError,
    SandboxResult,
    SandboxUnavailableError,
)
from initrunner.agent.schema.security import BindMount, SandboxConfig

if TYPE_CHECKING:
    from initrunner.audit.logger import AuditLogger
    from initrunner.audit.null import NullAuditLogger

logger = logging.getLogger(__name__)

_SYSTEM_RO_BINDS = [
    "/usr",
    "/bin",
    "/lib",
    "/lib64",
    "/etc/resolv.conf",
    "/etc/ssl/certs",
    "/etc/alternatives",
]

_DEFAULT_ENV_PASSTHROUGH = ("PATH", "HOME", "LANG", "TERM")

_systemd_run_checked = False
_systemd_run_available = False


def _read_sysctl(path: str) -> str | None:
    """Read an integer sysctl from /proc/sys. None if unreadable."""
    try:
        return Path(path).read_text().strip()
    except OSError:
        return None


def _diagnose_probe_failure(stderr: str) -> str:
    """Build a remediation string tailored to what actually blocked bwrap.

    Reads the relevant sysctls so users see the specific fix for their host
    instead of a generic list.
    """
    userns_clone = _read_sysctl("/proc/sys/kernel/unprivileged_userns_clone")
    apparmor_restrict = _read_sysctl("/proc/sys/kernel/apparmor_restrict_unprivileged_userns")
    uid_map_denied = "setting up uid map" in stderr or "Permission denied" in stderr

    lines: list[str] = []

    if userns_clone == "0":
        lines.append(
            "Unprivileged user namespaces are disabled in the kernel. Enable:\n"
            "  sudo sysctl -w kernel.unprivileged_userns_clone=1"
        )
    elif apparmor_restrict == "1" and uid_map_denied:
        lines.append(
            "Ubuntu 24+/Debian 13 AppArmor is blocking unprivileged user "
            "namespaces. Fix options (pick one):\n"
            "  1. Install a bwrap AppArmor profile (recommended, keeps system "
            "hardening):\n"
            "     sudo apt install --reinstall bubblewrap apparmor\n"
            "     sudo systemctl reload apparmor\n"
            "  2. Relax the global restriction (reduces hardening for all apps):\n"
            "     sudo sysctl -w kernel.apparmor_restrict_unprivileged_userns=0\n"
            "  3. Switch your role to backend: docker or backend: auto"
        )
    else:
        lines.append(
            "Check these kernel settings:\n"
            "  sudo sysctl kernel.unprivileged_userns_clone                "
            "(must be 1)\n"
            "  sudo sysctl kernel.apparmor_restrict_unprivileged_userns    "
            "(must be 0 on Ubuntu 24+)\n"
            "Or switch to backend: docker."
        )
    return "\n".join(lines)


def _check_systemd_run() -> bool:
    """Check if systemd-run --user is functional (cached)."""
    global _systemd_run_checked, _systemd_run_available
    if _systemd_run_checked:
        return _systemd_run_available
    _systemd_run_checked = True
    if not shutil.which("systemd-run"):
        _systemd_run_available = False
        return False
    try:
        result = subprocess.run(
            ["systemd-run", "--user", "--scope", "--quiet", "--", "/bin/true"],
            capture_output=True,
            timeout=5,
        )
        _systemd_run_available = result.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        _systemd_run_available = False
    return _systemd_run_available


class BwrapBackend:
    """Run tool commands inside a bubblewrap sandbox (Linux only)."""

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
        self._limits_warned = False

    @property
    def name(self) -> str:
        return "bwrap"

    def preflight(self) -> None:
        if sys.platform != "linux":
            raise SandboxUnavailableError(
                backend="bwrap",
                reason="bubblewrap is Linux-only",
                remediation=(
                    "Use backend: docker on this platform, or backend: auto to pick automatically."
                ),
            )
        if not shutil.which("bwrap"):
            raise SandboxUnavailableError(
                backend="bwrap",
                reason="bwrap not found on PATH",
                remediation=(
                    "Install bubblewrap:\n"
                    "  Debian/Ubuntu: apt install bubblewrap\n"
                    "  Fedora: dnf install bubblewrap\n"
                    "  Arch: pacman -S bubblewrap"
                ),
            )
        try:
            result = subprocess.run(
                ["bwrap", "--ro-bind", "/usr", "/usr", "--", "/bin/true"],
                capture_output=True,
                timeout=5,
            )
            if result.returncode != 0:
                stderr = result.stderr.decode("utf-8", errors="replace").strip()
                raise SandboxUnavailableError(
                    backend="bwrap",
                    reason=f"bubblewrap functional probe failed: {stderr}",
                    remediation=_diagnose_probe_failure(stderr),
                )
        except subprocess.TimeoutExpired:
            raise SandboxUnavailableError(
                backend="bwrap",
                reason="bubblewrap probe timed out",
                remediation="Check that bubblewrap is installed correctly.",
            ) from None
        except OSError as exc:
            raise SandboxUnavailableError(
                backend="bwrap",
                reason=f"bubblewrap probe failed: {exc}",
                remediation="Check that bubblewrap is installed correctly.",
            ) from None

    def _build_cmd(
        self,
        argv: list[str],
        *,
        env: Mapping[str, str],
        cwd: Path,
        extra_mounts: Sequence[BindMount],
        net: Literal["none", "bridge", "host"],
        stdin_used: bool,
    ) -> list[str]:
        if net == "bridge":
            raise SandboxConfigError(
                "network: bridge is not supported by the bwrap backend. "
                "Use network: none or network: host."
            )

        cmd = ["bwrap"]
        cmd.extend(
            [
                "--unshare-user",
                "--unshare-pid",
                "--unshare-uts",
                "--unshare-ipc",
                "--unshare-cgroup",
                "--die-with-parent",
            ]
        )

        if net == "none":
            cmd.append("--unshare-net")

        if not sys.stdin.isatty():
            cmd.append("--new-session")

        # Clean environment
        cmd.append("--clearenv")
        scrubbed = scrub_env()
        for key in _DEFAULT_ENV_PASSTHROUGH:
            value = scrubbed.get(key)
            if value is not None:
                cmd.extend(["--setenv", key, value])
        for key in self._config.env_passthrough:
            value = scrubbed.get(key)
            if value is not None:
                cmd.extend(["--setenv", key, value])
        for key, value in env.items():
            cmd.extend(["--setenv", key, value])

        # System read-only mounts
        for path in _SYSTEM_RO_BINDS:
            if Path(path).exists():
                cmd.extend(["--ro-bind", path, path])

        # Configured read paths
        for path in self._config.allowed_read_paths:
            if Path(path).exists():
                cmd.extend(["--ro-bind", path, path])

        # Configured write paths
        for path in self._config.allowed_write_paths:
            p = Path(path)
            p.mkdir(parents=True, exist_ok=True)
            cmd.extend(["--bind", path, path])

        # Configured bind mounts
        for mount in self._config.bind_mounts:
            source = mount.source
            if not Path(source).is_absolute() and self._role_dir:
                source = str(self._role_dir / source)
            flag = "--ro-bind" if mount.read_only else "--bind"
            cmd.extend([flag, source, mount.target])

        # Tool-internal extra mounts (trusted, no validation)
        for mount in extra_mounts:
            flag = "--ro-bind" if mount.read_only else "--bind"
            cmd.extend([flag, mount.source, mount.target])

        # Working directory
        cmd.extend(["--bind", str(cwd), "/work"])

        # Role directory (read-only)
        if self._role_dir and self._role_dir.exists():
            cmd.extend(["--ro-bind", str(self._role_dir), "/role"])

        # Virtual filesystems
        cmd.extend(["--tmpfs", "/tmp"])
        cmd.extend(["--proc", "/proc"])
        cmd.extend(["--dev", "/dev"])

        cmd.extend(["--chdir", "/work"])
        cmd.append("--")
        cmd.extend(argv)
        return cmd

    def _wrap_with_limits(
        self,
        cmd: list[str],
        memory_limit: str | None,
        cpu_limit: float | None,
    ) -> list[str]:
        ml = memory_limit or self._config.memory_limit
        cl = cpu_limit or self._config.cpu_limit

        if not _check_systemd_run():
            if not self._limits_warned:
                self._limits_warned = True
                logger.warning(
                    "systemd-run --user not available; "
                    "memory_limit and cpu_limit will not be enforced under bwrap"
                )
            return cmd

        wrapper = ["systemd-run", "--user", "--scope", "--quiet"]
        wrapper.extend(["-p", f"MemoryMax={ml}"])
        cpu_pct = int(cl * 100)
        wrapper.extend(["-p", f"CPUQuota={cpu_pct}%"])
        wrapper.append("--")
        wrapper.extend(cmd)
        return wrapper

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
        cmd = self._build_cmd(
            argv,
            env=env,
            cwd=cwd,
            extra_mounts=extra_mounts,
            net=net,
            stdin_used=stdin is not None,
        )
        cmd = self._wrap_with_limits(cmd, memory_limit, cpu_limit)

        t0 = time.monotonic()
        try:
            result = subprocess.run(
                cmd,
                input=stdin,
                capture_output=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            raise SubprocessTimeout(int(timeout)) from None

        elapsed = (time.monotonic() - t0) * 1000

        self._audit.log_security_event(
            "sandbox.exec",
            agent_name=self._agent_name,
            details=(
                f"backend=bwrap argv0={argv[0] if argv else ''} "
                f"rc={result.returncode} duration_ms={elapsed:.0f}"
            ),
        )

        return SandboxResult(
            stdout=result.stdout.decode("utf-8", errors="replace"),
            stderr=result.stderr.decode("utf-8", errors="replace"),
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
