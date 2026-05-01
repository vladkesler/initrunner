"""SSHBackend -- remote execution over OpenSSH.

SSH is *remote execution*, not a kernel sandbox. It runs commands on an existing
remote filesystem with whatever isolation that host already provides. Use it for
*where* code runs, not for *containing* untrusted code.

v1 contract: argv + env + stdin -> stdout/stderr/rc on the remote host.
v1 does NOT support extra_mounts, bind_mounts, network isolation, or resource
caps. Tools that stage local files (e.g. python_exec) are not supported in v1.
"""

from __future__ import annotations

import logging
import os
import shlex
import shutil
import subprocess
import tempfile
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from initrunner.agent._subprocess import SubprocessTimeout
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


class SSHBackend:
    """Run tool commands on a remote host via OpenSSH.

    Auth comes from the user's OpenSSH config: ``Host``, ``IdentityFile``,
    ``User``, ``Port`` are resolved via ``~/.ssh/config`` and ``ssh-agent``.
    Per-call latency is amortized via ControlMaster multiplexing.
    """

    def __init__(
        self,
        config: SandboxConfig,
        *,
        role_dir: Path | None = None,
        audit: AuditLogger | NullAuditLogger | None = None,
        agent_name: str = "",
    ) -> None:
        if config.ssh is None:
            raise SandboxConfigError(
                "sandbox.backend is 'ssh' but sandbox.ssh is unset. "
                "Add `ssh: { host: <host> }` to your role's security.sandbox config."
            )
        self._config = config
        self._ssh = config.ssh
        self._role_dir = role_dir
        self._agent_name = agent_name
        self._control_dir = Path(tempfile.mkdtemp(prefix="initrunner-ssh-"))
        self._control_path = self._control_dir / "ctl.sock"
        from initrunner.audit.null import NullAuditLogger as _Null

        self._audit: AuditLogger | _Null = audit or _Null()

    @property
    def name(self) -> str:
        return "ssh"

    def close(self) -> None:
        """Tear down the ControlMaster socket and remove the temp dir."""
        try:
            subprocess.run(
                [*self._ssh_base_cmd(), "-O", "exit", "--", self._ssh.host],
                capture_output=True,
                timeout=5,
                env=os.environ.copy(),
            )
        except (subprocess.SubprocessError, OSError):
            pass
        shutil.rmtree(self._control_dir, ignore_errors=True)

    def __del__(self) -> None:
        self.close()

    def _ssh_base_cmd(self) -> list[str]:
        """Build the ssh argv prefix: binary + options, no host or remote cmd."""
        cmd: list[str] = ["ssh"]
        if self._ssh.config_file is not None:
            cmd.extend(["-F", str(self._ssh.config_file)])
        if self._ssh.identity_file is not None:
            cmd.extend(["-i", str(self._ssh.identity_file)])
        cmd.extend(
            [
                "-o",
                "BatchMode=yes",
                "-o",
                f"ConnectTimeout={int(self._ssh.connect_timeout)}",
                "-o",
                "ControlMaster=auto",
                "-o",
                f"ControlPath={self._control_path}",
                "-o",
                f"ControlPersist={self._ssh.control_persist}",
            ]
        )
        return cmd

    def preflight(self) -> None:
        cmd = [*self._ssh_base_cmd(), "--", self._ssh.host, "true"]
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                timeout=max(10, int(self._ssh.connect_timeout) + 5),
                env=os.environ.copy(),
            )
        except FileNotFoundError as exc:
            raise SandboxUnavailableError(
                backend="ssh",
                reason="ssh client not found on PATH",
                remediation=(
                    "Install OpenSSH:\n"
                    "  Debian/Ubuntu: apt install openssh-client\n"
                    "  macOS: ssh ships with the OS\n"
                    "  Fedora: dnf install openssh-clients"
                ),
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise SandboxUnavailableError(
                backend="ssh",
                reason=f"ssh connection to {self._ssh.host!r} timed out",
                remediation=(
                    f"Check that the host is reachable and that '{self._ssh.host}' "
                    f"is configured in ~/.ssh/config. Try: ssh {self._ssh.host} true"
                ),
            ) from exc

        if result.returncode != 0:
            stderr = result.stderr.decode("utf-8", errors="replace").strip()
            raise SandboxUnavailableError(
                backend="ssh",
                reason=(
                    f"ssh probe to {self._ssh.host!r} returned rc={result.returncode}"
                    + (f": {stderr}" if stderr else "")
                ),
                remediation=(
                    "Verify your auth and host config:\n"
                    f"  1. Try: ssh -o BatchMode=yes {self._ssh.host} true\n"
                    "  2. Confirm ssh-agent is running: ssh-add -l\n"
                    "  3. Check ~/.ssh/config for the host alias\n"
                    "  4. If using identity_file, confirm the key path is correct"
                ),
            )

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
        if extra_mounts:
            raise SandboxConfigError(
                "extra_mounts is not supported on the SSH backend in v1. "
                "Tools that stage local files into the sandbox (e.g. python_exec) "
                "have no shared filesystem with the remote host. Use shell tools "
                "with a remote-installed interpreter, or wait for v1.1 stdin/SCP support."
            )

        # Build the remote command. Local cwd is intentionally ignored -- the
        # remote host's filesystem is unrelated to the local role_dir. Use
        # ssh.remote_cwd if the user wants a specific working directory.
        remote_cmd = _build_remote_command(
            argv=argv,
            env=dict(env),
            remote_cwd=self._ssh.remote_cwd,
        )

        ssh_cmd = [*self._ssh_base_cmd(), "--", self._ssh.host, remote_cmd]

        # Local SSH process MUST keep SSH_AUTH_SOCK / SSH_AGENT_PID so ssh-agent
        # auth works. scrub_env() strips SSH_AUTH_SOCK -- never use it here.
        local_env = os.environ.copy()

        t0 = time.monotonic()
        try:
            result = subprocess.run(
                ssh_cmd,
                input=stdin,
                capture_output=True,
                timeout=timeout,
                env=local_env,
            )
        except subprocess.TimeoutExpired:
            self.close()
            raise SubprocessTimeout(int(timeout)) from None

        elapsed = (time.monotonic() - t0) * 1000

        argv0 = argv[0] if argv else ""
        self._audit.log_security_event(
            "sandbox.exec",
            agent_name=self._agent_name,
            details=(
                f"backend=ssh host={self._ssh.host} argv0={argv0} "
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


def _build_remote_command(
    *,
    argv: list[str],
    env: dict[str, str],
    remote_cwd: str | None,
) -> str:
    """Build the single shell-quoted command string sent to the remote host.

    Form: ``[cd <cwd> && ] [env VAR=val ...] <argv...>``

    ``env`` is scrubbed of sensitive keys before being injected; the sensitive-key
    list is shared with other sandbox backends so the same credentials never leak
    into a remote shell.
    """
    safe_env = _scrub_caller_env(env)

    parts: list[str] = []
    if remote_cwd:
        parts.append(f"cd {shlex.quote(remote_cwd)} &&")

    if safe_env:
        env_tokens = ["env"] + [f"{k}={shlex.quote(v)}" for k, v in safe_env.items()]
        parts.extend(env_tokens)

    parts.extend(shlex.quote(a) for a in argv)
    return " ".join(parts)


def _scrub_caller_env(env: dict[str, str]) -> dict[str, str]:
    """Strip sensitive keys from a caller-provided env mapping.

    ``scrub_env()`` reads ``os.environ``; we want the same filter applied to
    arbitrary mappings, so we re-implement the predicate here over the input.
    """
    if not env:
        return env

    from initrunner.agent._subprocess import (
        DEFAULT_ENV_ALLOWLIST,
        DEFAULT_SENSITIVE_ENV_PREFIXES,
        DEFAULT_SENSITIVE_ENV_SUFFIXES,
    )

    upper_prefixes = tuple(p.upper() for p in DEFAULT_SENSITIVE_ENV_PREFIXES)
    upper_suffixes = tuple(s.upper() for s in DEFAULT_SENSITIVE_ENV_SUFFIXES)

    out: dict[str, str] = {}
    for k, v in env.items():
        ku = k.upper()
        if k in DEFAULT_ENV_ALLOWLIST:
            out[k] = v
            continue
        if any(ku.startswith(p) for p in upper_prefixes):
            continue
        if any(ku.endswith(s) for s in upper_suffixes):
            continue
        out[k] = v
    return out


__all__ = ["SSHBackend", "_build_remote_command", "_scrub_caller_env"]
