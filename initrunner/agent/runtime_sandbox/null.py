"""NullBackend -- no isolation, delegates to bare subprocess."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Literal

from initrunner.agent._subprocess import scrub_env
from initrunner.agent.runtime_sandbox.base import SandboxResult, _timed_subprocess
from initrunner.agent.schema.security import BindMount


def _translate_path(arg: str, cwd: Path, extra_mounts: Sequence[BindMount]) -> str:
    """Translate sandbox-style paths to host paths for NullBackend.

    Tools pass argv like ``[python, "/work/_run.py"]`` assuming the sandbox
    mount layout. Without isolation we need the original host path instead.
    Maps ``/work`` to *cwd* and each mount target to its source.
    """
    if not arg.startswith("/"):
        return arg
    if arg == "/work" or arg.startswith("/work/"):
        return str(cwd) + arg[len("/work") :]
    for mount in extra_mounts:
        if arg == mount.target or arg.startswith(mount.target + "/"):
            return mount.source + arg[len(mount.target) :]
    return arg


class NullBackend:
    """Runs commands directly on the host with no isolation.

    Used only when ``backend: none`` is explicitly configured.
    """

    @property
    def name(self) -> str:
        return "none"

    def preflight(self) -> None:
        pass

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
        run_env = dict(scrub_env())
        run_env.update(env)
        translated = [_translate_path(arg, cwd, extra_mounts) for arg in argv]
        return _timed_subprocess(
            translated,
            stdin=stdin,
            env=run_env,
            cwd=str(cwd),
            timeout=timeout,
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
