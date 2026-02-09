"""Systemd user unit integration for compose services."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path


class SystemdError(Exception):
    """Raised when a systemd operation fails."""


@dataclass
class UnitInfo:
    """Result of a unit install operation."""

    unit_name: str
    unit_path: Path
    compose_name: str
    compose_path: Path


_UNIT_DIR = Path.home() / ".config" / "systemd" / "user"

_UNIT_TEMPLATE = """\
# Managed by initrunner -- do not edit manually.
# Compose: {compose_name}
# Source:  {compose_path}
# Installed: {timestamp}

[Unit]
Description=InitRunner Compose: {compose_name}
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart={exec_start}
WorkingDirectory={working_dir}
Restart=on-failure
RestartSec=10

# Environment — shell env vars (e.g. from .bashrc) are NOT inherited.
# Add secrets to the .env file or use --env-file during install.
EnvironmentFile=-{working_dir}/.env
EnvironmentFile=-{home}/.initrunner/.env
{extra_env_file}
# Logging
StandardOutput=journal
StandardError=journal
SyslogIdentifier=initrunner-{sanitized_name}

# Shutdown
KillSignal=SIGTERM
TimeoutStopSec=30

# Security (user-level hardening)
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=read-only
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
RestrictRealtime=true
RestrictSUIDSGID=true
LockPersonality=true
RestrictNamespaces=true
SystemCallArchitectures=native
ReadWritePaths={read_write_paths}

[Install]
WantedBy=default.target
"""

_ENV_TEMPLATE = """\
# Environment file for initrunner compose: {compose_name}
# Uncomment and fill in the values your agents need.
# This file is referenced by the systemd unit as EnvironmentFile.

# OPENAI_API_KEY=sk-...
# ANTHROPIC_API_KEY=sk-ant-...
# OLLAMA_HOST=http://localhost:11434
"""


def _systemd_escape_arg(value: str) -> str:
    """Quote a value for systemd ExecStart if it contains spaces."""
    s = str(value)
    if " " not in s and '"' not in s and "\\" not in s:
        return s
    s = s.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{s}"'


def sanitize_unit_name(compose_name: str, compose_path: Path | None = None) -> str:
    """Convert a compose name to a safe systemd unit name component.

    Replaces non-alphanumeric/dash/underscore chars with dashes,
    collapses consecutive dashes, and strips leading/trailing dashes.

    If *compose_path* is given and a unit already exists at the target path
    with a different WorkingDirectory, appends a 4-char hash to disambiguate.
    """
    sanitized = re.sub(r"[^a-zA-Z0-9_-]", "-", compose_name)
    sanitized = re.sub(r"-{2,}", "-", sanitized)
    sanitized = sanitized.strip("-")
    if not sanitized:
        sanitized = "unnamed"

    if compose_path is not None:
        existing_unit = _UNIT_DIR / f"initrunner-{sanitized}.service"
        if existing_unit.exists():
            content = existing_unit.read_text()
            work_dir = str(compose_path.resolve().parent)
            if f"WorkingDirectory={work_dir}" not in content:
                path_hash = hashlib.sha256(str(compose_path.resolve()).encode()).hexdigest()[:4]
                sanitized = f"{sanitized}-{path_hash}"

    return sanitized


def unit_name_for(compose_name: str) -> str:
    """Return the full systemd unit name for a compose project."""
    return f"initrunner-{sanitize_unit_name(compose_name)}.service"


def check_systemd_available() -> None:
    """Raise SystemdError if systemctl is not on PATH."""
    if shutil.which("systemctl") is None:
        raise SystemdError(
            "systemctl not found. systemd integration requires a Linux system with systemd."
        )


def check_linger_enabled() -> bool:
    """Check whether user lingering is enabled.

    Returns True if linger is enabled or if the check cannot be performed
    (e.g., loginctl not available). Only returns False when loginctl
    explicitly reports Linger=no.
    """
    loginctl = shutil.which("loginctl")
    if loginctl is None:
        return True

    user = os.environ.get("USER", "")
    if not user:
        return True

    try:
        result = subprocess.run(
            [loginctl, "show-user", user, "--property=Linger"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.stdout.strip() != "Linger=no"
    except (subprocess.TimeoutExpired, OSError):
        return True


def find_initrunner_executable() -> str:
    """Find the absolute path to the initrunner executable.

    Tries ``shutil.which("initrunner")`` first, then falls back to
    ``sys.executable -m initrunner``.
    """
    which = shutil.which("initrunner")
    if which is not None:
        return str(Path(which).resolve())
    return f"{sys.executable} -m initrunner"


def generate_unit_content(
    compose_name: str,
    compose_path: Path,
    *,
    executable: str | None = None,
    env_file: Path | None = None,
) -> str:
    """Render a systemd unit file for the given compose project."""
    compose_path = compose_path.resolve()
    sanitized = sanitize_unit_name(compose_name, compose_path)
    exe = executable or find_initrunner_executable()

    # Build ExecStart with quoting for paths that may contain spaces.
    # Handle the `sys.executable -m initrunner` fallback form.
    if " -m " in exe:
        parts = exe.split(" -m ", 1)
        exec_start = (
            f"{_systemd_escape_arg(parts[0])} -m {parts[1]} "
            f"compose up {_systemd_escape_arg(str(compose_path))}"
        )
    else:
        exec_start = (
            f"{_systemd_escape_arg(exe)} compose up {_systemd_escape_arg(str(compose_path))}"
        )

    working_dir = compose_path.parent
    home = Path.home()
    read_write_paths = (
        f"{_systemd_escape_arg(str(working_dir))} {_systemd_escape_arg(str(home / '.initrunner'))}"
    )

    extra_env = ""
    if env_file is not None:
        extra_env = f"EnvironmentFile={env_file.resolve()}\n"

    return _UNIT_TEMPLATE.format(
        compose_name=compose_name,
        compose_path=compose_path,
        timestamp=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        exec_start=exec_start,
        working_dir=working_dir,
        home=home,
        sanitized_name=sanitized,
        extra_env_file=extra_env,
        read_write_paths=read_write_paths,
    )


def generate_env_template(compose_name: str) -> str:
    """Return placeholder .env content for a compose project."""
    return _ENV_TEMPLATE.format(compose_name=compose_name)


def install_unit(
    compose_name: str,
    compose_path: Path,
    *,
    force: bool = False,
    executable: str | None = None,
    env_file: Path | None = None,
) -> UnitInfo:
    """Write a systemd user unit file and reload the daemon.

    Raises SystemdError on failures, or if the unit already exists
    and *force* is False.
    """
    check_systemd_available()
    compose_path = compose_path.resolve()
    sanitized = sanitize_unit_name(compose_name, compose_path)
    unit_name = f"initrunner-{sanitized}.service"
    unit_path = _UNIT_DIR / unit_name

    if unit_path.exists() and not force:
        raise SystemdError(
            f"Unit {unit_name} already exists at {unit_path}. Use --force to overwrite."
        )

    _UNIT_DIR.mkdir(parents=True, exist_ok=True)

    content = generate_unit_content(
        compose_name, compose_path, executable=executable, env_file=env_file
    )
    # Use os.open() with restrictive permissions (0o600) so the unit file
    # is never world-readable, even briefly.
    fd = os.open(
        str(unit_path),
        os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
        0o600,
    )
    try:
        os.write(fd, content.encode())
    finally:
        os.close(fd)

    _systemctl("daemon-reload")

    return UnitInfo(
        unit_name=unit_name,
        unit_path=unit_path,
        compose_name=compose_name,
        compose_path=compose_path,
    )


def uninstall_unit(compose_name: str) -> Path:
    """Stop, disable, and remove a systemd user unit file.

    Returns the path of the removed unit file.
    Raises SystemdError if the unit file does not exist.
    """
    check_systemd_available()
    sanitized = sanitize_unit_name(compose_name)
    unit_name = f"initrunner-{sanitized}.service"
    unit_path = _UNIT_DIR / unit_name

    if not unit_path.exists():
        raise SystemdError(f"Unit {unit_name} not found at {unit_path}.")

    # Best-effort stop and disable — don't fail if the service isn't running.
    _systemctl("stop", unit_name, check=False)
    _systemctl("disable", unit_name, check=False)

    unit_path.unlink()
    _systemctl("daemon-reload")

    return unit_path


def get_unit_status(compose_name: str) -> str:
    """Return the ``systemctl status`` output for a compose unit."""
    check_systemd_available()
    sanitized = sanitize_unit_name(compose_name)
    unit_name = f"initrunner-{sanitized}.service"
    # status exits non-zero for inactive/failed units — don't check.
    result = _systemctl("status", unit_name, check=False, capture=True)
    return result.stdout


def resolve_compose_name(name_or_path: str) -> str:
    """Resolve a compose name from a name string or YAML path.

    If the argument looks like a path (has a YAML extension or exists on disk),
    load the compose definition and return ``metadata.name``.
    If it has a YAML extension but does not exist, raise ``FileNotFoundError``.
    Otherwise, return the argument as-is (assumed to be a compose name).
    """
    p = Path(name_or_path)
    is_yaml = p.suffix in (".yaml", ".yml")

    if is_yaml or p.exists():
        if not p.exists():
            raise FileNotFoundError(f"Compose file not found: {name_or_path}")
        from initrunner.compose.loader import load_compose

        compose = load_compose(p)
        return compose.metadata.name

    return name_or_path


def _systemctl(
    *args: str,
    check: bool = True,
    capture: bool = False,
) -> subprocess.CompletedProcess[str]:
    """Run ``systemctl --user <args>``."""
    cmd = ["systemctl", "--user", *args]
    try:
        return subprocess.run(
            cmd,
            capture_output=capture,
            text=True,
            timeout=30,
            check=check,
        )
    except subprocess.CalledProcessError as e:
        raise SystemdError(f"systemctl command failed: {' '.join(cmd)}\n{e.stderr or ''}") from e
    except subprocess.TimeoutExpired as e:
        raise SystemdError(f"systemctl command timed out: {' '.join(cmd)}") from e
