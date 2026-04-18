"""Docker container sandbox for tool execution."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from pathlib import Path
from uuid import uuid4

from initrunner.agent._subprocess import scrub_env
from initrunner.agent.schema.security import SandboxConfig

logger = logging.getLogger(__name__)


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
            "Docker is required but the Docker CLI is not available or the daemon is not running"
        )


def ensure_image_available(image: str, *, timeout: int = 300) -> None:
    """Pull *image* if not locally available.

    Raises :class:`DockerNotAvailableError` on failure with a message that
    distinguishes private/auth images from network issues.
    """
    try:
        result = subprocess.run(
            ["docker", "image", "inspect", image],
            capture_output=True,
            timeout=10,
        )
        if result.returncode == 0:
            return  # already available
    except (subprocess.TimeoutExpired, OSError):
        pass  # fall through to pull

    logger.info("Pulling Docker image '%s'...", image)
    try:
        result = subprocess.run(
            ["docker", "pull", image],
            capture_output=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        raise DockerNotAvailableError(
            f"Timed out pulling Docker image '{image}' after {timeout}s. "
            f"If this is a large image, try running `docker pull {image}` manually first."
        ) from None
    except OSError as exc:
        raise DockerNotAvailableError(f"Failed to pull Docker image '{image}': {exc}") from None

    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", errors="replace").strip()
        raise DockerNotAvailableError(
            f"Failed to pull Docker image '{image}'. "
            f"If this is a private image, run `docker pull {image}` manually first.\n"
            f"Docker output: {stderr}"
        )
    logger.info("Docker image '%s' pulled successfully.", image)


def _generate_container_name() -> str:
    """Generate a unique container name for tracking and cleanup."""
    return f"initrunner-{uuid4().hex[:12]}"


def _kill_container(name: str) -> None:
    """Best-effort kill and remove a container by name."""
    try:
        subprocess.run(
            ["docker", "rm", "-f", name],
            capture_output=True,
            timeout=5,
        )
    except Exception:
        pass  # cleanup failure must not mask the original error


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
    config: SandboxConfig,
    *,
    container_name: str | None = None,
    work_dir: str | None = None,
    extra_mounts: list[tuple[str, str, bool]] | None = None,
    interactive: bool = False,
    role_dir: Path | None = None,
    env: dict[str, str] | None = None,
) -> list[str]:
    """Build the ``docker run --rm`` command prefix (without the final command)."""
    cmd = ["docker", "run", "--rm", "--init"]

    if container_name:
        cmd.extend(["--name", container_name])
    cmd.extend(["--label", "initrunner.managed=true"])

    cmd.extend(["--network", config.network])
    cmd.extend(["-m", config.memory_limit])
    cmd.extend(["--cpus", str(config.cpu_limit)])

    if config.read_only_rootfs:
        cmd.append("--read-only")
        cmd.extend(["--tmpfs", "/tmp:rw,noexec,nosuid,size=64m"])

    cmd.extend(["--pids-limit", "256"])

    docker = config.docker
    has_writable_mount = work_dir is not None or any(not m.read_only for m in config.bind_mounts)
    if docker.user == "auto":
        if has_writable_mount:
            cmd.extend(["--user", f"{os.getuid()}:{os.getgid()}"])
    elif docker.user is not None:
        cmd.extend(["--user", docker.user])

    for mount in config.bind_mounts:
        resolved = _resolve_mount_source(mount.source, role_dir)
        if not Path(resolved).exists():
            raise ValueError(
                f"Bind mount source '{mount.source}' (resolved to '{resolved}') "
                f"does not exist on the host."
            )
        ro = ":ro" if mount.read_only else ""
        cmd.extend(["-v", f"{resolved}:{mount.target}{ro}"])

    if extra_mounts:
        for src, tgt, read_only in extra_mounts:
            ro = ":ro" if read_only else ""
            cmd.extend(["-v", f"{src}:{tgt}{ro}"])

    if work_dir:
        cmd.extend(["-v", f"{work_dir}:/work", "-w", "/work"])

    scrubbed = scrub_env()
    for key in config.env_passthrough:
        value = scrubbed.get(key)
        if value is not None:
            cmd.extend(["-e", f"{key}={value}"])

    if env:
        for key, value in env.items():
            cmd.extend(["-e", f"{key}={value}"])

    if interactive:
        cmd.append("-i")

    cmd.extend(docker.extra_args)
    cmd.append(docker.image)
    return cmd


def _format_oom_hint(returncode: int, stderr: str, memory_limit: str) -> str:
    """Append an OOM hint to *stderr* when the container was OOM-killed."""
    if returncode == 137:
        hint = (
            f"\nContainer killed (OOM). "
            f"Increase security.sandbox.memory_limit (current: {memory_limit})."
        )
        return stderr + hint
    return stderr
