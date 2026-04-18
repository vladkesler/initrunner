"""SandboxBackend protocol and shared types."""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol, runtime_checkable

from initrunner.agent.schema.security import BindMount


@dataclass(frozen=True)
class SandboxResult:
    """Result of a sandboxed subprocess execution."""

    stdout: str
    stderr: str
    returncode: int
    duration_ms: float


class SandboxUnavailableError(RuntimeError):
    """Raised when a requested sandbox backend is not available on this host."""

    def __init__(self, backend: str, reason: str, remediation: str) -> None:
        self.backend = backend
        self.reason = reason
        self.remediation = remediation
        super().__init__(f"Sandbox backend '{backend}' unavailable: {reason}")


class SandboxConfigError(ValueError):
    """Raised when a sandbox configuration is invalid for the chosen backend."""


@runtime_checkable
class SandboxBackend(Protocol):
    """Uniform interface for out-of-process tool isolation."""

    @property
    def name(self) -> str: ...

    def preflight(self) -> None:
        """Verify the backend is functional. Raises SandboxUnavailableError."""
        ...

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
        """Run a command inside the sandbox."""
        ...

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
        """Async variant of run(). Default delegates via anyio."""
        ...


def _timed_subprocess(
    cmd: list[str],
    *,
    stdin: bytes | None = None,
    env: dict[str, str],
    cwd: str | None = None,
    timeout: float,
) -> SandboxResult:
    """Run a subprocess and return a SandboxResult with timing."""
    import subprocess

    from initrunner.agent._subprocess import SubprocessTimeout

    t0 = time.monotonic()
    try:
        result = subprocess.run(
            cmd,
            input=stdin,
            capture_output=True,
            timeout=timeout,
            cwd=cwd,
            env=env,
        )
    except subprocess.TimeoutExpired:
        raise SubprocessTimeout(int(timeout)) from None
    elapsed = (time.monotonic() - t0) * 1000
    return SandboxResult(
        stdout=result.stdout.decode("utf-8", errors="replace"),
        stderr=result.stderr.decode("utf-8", errors="replace"),
        returncode=result.returncode,
        duration_ms=elapsed,
    )
