"""Docker container sandbox for tool execution."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from initrunner.agent._subprocess import SubprocessTimeout, scrub_env
from initrunner.agent.schema.security import DockerSandboxConfig


class DockerNotAvailableError(RuntimeError):
    """Raised when Docker is required but not available."""


def check_docker_available() -> bool:
    """Return True if Docker CLI exists and the daemon is reachable."""
    if not shutil.which("docker"):
        return False
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            timeout=5,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def require_docker() -> None:
    """Raise :class:`DockerNotAvailableError` if Docker is not available."""
    if not check_docker_available():
        raise DockerNotAvailableError(
            "Docker is required (security.docker.enabled is true) "
            "but the Docker CLI is not available or the daemon is not running"
        )


def _resolve_mount_source(source: str, role_dir: Path | None) -> str:
    """Resolve a mount source path.

    Relative paths are resolved against *role_dir* first, then
    :meth:`Path.resolve` for absolute normalization.
    """
    p = Path(source)
    if not p.is_absolute() and role_dir is not None:
        p = role_dir / p
    return str(p.resolve())


def _build_docker_cmd(
    config: DockerSandboxConfig,
    *,
    work_dir: str | None = None,
    extra_mounts: list[tuple[str, str, bool]] | None = None,
    interactive: bool = False,
    role_dir: Path | None = None,
    env: dict[str, str] | None = None,
) -> list[str]:
    """Build the ``docker run --rm`` command prefix (without the final command)."""
    cmd = ["docker", "run", "--rm"]

    cmd.extend(["--network", config.network])
    cmd.extend(["-m", config.memory_limit])
    cmd.extend(["--cpus", str(config.cpu_limit)])

    if config.read_only_rootfs:
        cmd.append("--read-only")
        cmd.extend(["--tmpfs", "/tmp:rw,noexec,nosuid,size=64m"])

    cmd.extend(["--pids-limit", "256"])

    # Bind mounts from config
    for mount in config.bind_mounts:
        resolved = _resolve_mount_source(mount.source, role_dir)
        ro = ":ro" if mount.read_only else ""
        cmd.extend(["-v", f"{resolved}:{mount.target}{ro}"])

    # Extra mounts (e.g. code file mounts)
    if extra_mounts:
        for src, tgt, read_only in extra_mounts:
            ro = ":ro" if read_only else ""
            cmd.extend(["-v", f"{src}:{tgt}{ro}"])

    # Working directory mount
    if work_dir:
        cmd.extend(["-v", f"{work_dir}:/work", "-w", "/work"])

    # Env passthrough (filtered through scrub_env)
    scrubbed = scrub_env()
    for key in config.env_passthrough:
        value = scrubbed.get(key)
        if value is not None:
            cmd.extend(["-e", f"{key}={value}"])

    # Explicit env vars (e.g. from script tools)
    if env:
        for key, value in env.items():
            cmd.extend(["-e", f"{key}={value}"])

    if interactive:
        cmd.append("-i")

    # Extra args from config (already validated by schema)
    cmd.extend(config.extra_args)

    cmd.append(config.image)
    return cmd


def docker_run_command(
    tokens: list[str],
    config: DockerSandboxConfig,
    *,
    timeout: int,
    work_dir: str | None = None,
    role_dir: Path | None = None,
) -> tuple[str, str, int]:
    """Run a shell command inside a Docker container.

    Returns ``(stdout, stderr, returncode)``.

    Raises:
        SubprocessTimeout: If the container exceeds *timeout* seconds.
    """
    cmd = _build_docker_cmd(config, work_dir=work_dir, role_dir=role_dir)
    cmd.extend(tokens)

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        raise SubprocessTimeout(timeout) from None

    return (
        result.stdout.decode("utf-8", errors="replace"),
        result.stderr.decode("utf-8", errors="replace"),
        result.returncode,
    )


def docker_run_python(
    code: str,
    config: DockerSandboxConfig,
    *,
    timeout: int,
    work_dir: str | None = None,
    role_dir: Path | None = None,
) -> tuple[str, str, int]:
    """Run Python code inside a Docker container.

    Writes *code* to a temp file, bind-mounts it at ``/code/_run.py``,
    and runs ``python /code/_run.py``.  Temp directory is always cleaned up.

    Returns ``(stdout, stderr, returncode)``.

    Raises:
        SubprocessTimeout: If the container exceeds *timeout* seconds.
    """
    tmp_dir = tempfile.mkdtemp(prefix="initrunner_docker_py_")
    try:
        code_file = Path(tmp_dir) / "_run.py"
        code_file.write_text(code, encoding="utf-8")

        cmd = _build_docker_cmd(
            config,
            work_dir=work_dir,
            extra_mounts=[(tmp_dir, "/code", True)],
            role_dir=role_dir,
        )
        cmd.extend(["python", "/code/_run.py"])

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            raise SubprocessTimeout(timeout) from None

        return (
            result.stdout.decode("utf-8", errors="replace"),
            result.stderr.decode("utf-8", errors="replace"),
            result.returncode,
        )
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def docker_run_script(
    body: str,
    interpreter: str,
    config: DockerSandboxConfig,
    *,
    timeout: int,
    work_dir: str | None = None,
    env: dict[str, str] | None = None,
    role_dir: Path | None = None,
) -> tuple[str, str, int]:
    """Run a script inside a Docker container by piping *body* via stdin.

    Returns ``(stdout, stderr, returncode)``.

    Raises:
        SubprocessTimeout: If the container exceeds *timeout* seconds.
    """
    cmd = _build_docker_cmd(
        config,
        work_dir=work_dir,
        interactive=True,
        role_dir=role_dir,
        env=env,
    )
    cmd.append(interpreter)

    try:
        result = subprocess.run(
            cmd,
            input=body.encode("utf-8"),
            capture_output=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        raise SubprocessTimeout(timeout) from None

    return (
        result.stdout.decode("utf-8", errors="replace"),
        result.stderr.decode("utf-8", errors="replace"),
        result.returncode,
    )
