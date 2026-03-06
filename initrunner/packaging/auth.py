"""OCI registry credential resolution."""

from __future__ import annotations

import base64
import json
import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class OCIAuth:
    username: str
    password: str


def _get_oci_auth_path() -> Path:
    from initrunner.config import get_home_dir

    return get_home_dir() / "oci-auth.json"


def resolve_auth(registry: str) -> OCIAuth | None:
    """Resolve credentials for an OCI registry.

    Resolution order:
    1. INITRUNNER_OCI_USERNAME + INITRUNNER_OCI_PASSWORD env vars
    2. ~/.initrunner/oci-auth.json
    3. ~/.docker/config.json (base64 auth field only)
    """
    import os

    # 1. Env vars
    username = os.environ.get("INITRUNNER_OCI_USERNAME")
    password = os.environ.get("INITRUNNER_OCI_PASSWORD")
    if username and password:
        return OCIAuth(username=username, password=password)

    # 2. oci-auth.json
    auth = _load_oci_auth(registry)
    if auth is not None:
        return auth

    # 3. Docker config
    return load_docker_config_auth(registry)


def save_auth(registry: str, username: str, password: str) -> None:
    """Save credentials to oci-auth.json (mode 0o600)."""
    import sys

    from initrunner._paths import ensure_private_dir

    auth_path = _get_oci_auth_path()
    ensure_private_dir(auth_path.parent)

    data: dict = {}
    if auth_path.exists():
        try:
            data = json.loads(auth_path.read_text())
        except (json.JSONDecodeError, OSError):
            data = {}

    if "auths" not in data:
        data["auths"] = {}

    encoded = base64.b64encode(f"{username}:{password}".encode()).decode()
    data["auths"][registry] = {"auth": encoded}

    auth_path.write_text(json.dumps(data, indent=2))
    if sys.platform != "win32":
        auth_path.chmod(0o600)


def _load_oci_auth(registry: str) -> OCIAuth | None:
    """Load credentials from oci-auth.json."""
    auth_path = _get_oci_auth_path()
    if not auth_path.exists():
        return None

    try:
        data = json.loads(auth_path.read_text())
    except (json.JSONDecodeError, OSError):
        return None

    auths = data.get("auths", {})
    entry = auths.get(registry)
    if not entry:
        return None

    return _decode_auth_entry(entry)


def load_docker_config_auth(registry: str) -> OCIAuth | None:
    """Parse ~/.docker/config.json for base64 auth. Warns on credential helpers."""
    docker_config = Path.home() / ".docker" / "config.json"
    if not docker_config.exists():
        return None

    try:
        data = json.loads(docker_config.read_text())
    except (json.JSONDecodeError, OSError):
        return None

    # Warn about unsupported credential helpers
    if data.get("credsStore") or data.get("credHelpers"):
        logger.warning(
            "Docker credential helpers not supported; use 'initrunner login <registry>' instead."
        )

    auths = data.get("auths", {})

    # Try exact match first, then try with/without https://
    entry = auths.get(registry)
    if entry is None:
        entry = auths.get(f"https://{registry}")
    if entry is None and registry.startswith("https://"):
        entry = auths.get(registry.removeprefix("https://"))

    if not entry:
        return None

    return _decode_auth_entry(entry)


def _decode_auth_entry(entry: dict) -> OCIAuth | None:
    """Decode a base64 auth entry."""
    auth_str = entry.get("auth")
    if not auth_str:
        return None

    try:
        decoded = base64.b64decode(auth_str).decode()
    except Exception:
        return None

    if ":" not in decoded:
        return None

    username, password = decoded.split(":", 1)
    return OCIAuth(username=username, password=password)
