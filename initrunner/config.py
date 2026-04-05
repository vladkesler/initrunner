"""Centralized path configuration for InitRunner.

Respects ``INITRUNNER_HOME`` env var, then ``XDG_DATA_HOME/initrunner``,
and falls back to ``~/.initrunner``.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def get_home_dir() -> Path:
    """Return the InitRunner data directory.

    Resolution order:
    1. ``INITRUNNER_HOME`` environment variable
    2. ``XDG_DATA_HOME/initrunner`` (if ``XDG_DATA_HOME`` is set)
    3. ``~/.initrunner``
    """
    env = os.environ.get("INITRUNNER_HOME")
    if env:
        return Path(env)
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return Path(xdg) / "initrunner"
    return Path.home() / ".initrunner"


def get_audit_db_path() -> Path:
    return get_home_dir() / "audit.db"


def get_stores_dir() -> Path:
    return get_home_dir() / "stores"


def get_memory_dir() -> Path:
    return get_home_dir() / "memory"


def get_roles_dir() -> Path:
    return get_home_dir() / "roles"


def get_skills_dir() -> Path:
    return get_home_dir() / "skills"


def get_global_env_path() -> Path:
    return get_home_dir() / ".env"


def get_oci_auth_path() -> Path:
    return get_home_dir() / "oci-auth.json"


def get_models_config_path() -> Path:
    return get_home_dir() / "models.yaml"


def get_bundles_cache_dir() -> Path:
    return get_home_dir() / "cache" / "bundles"


def get_mcp_cache_dir() -> Path:
    return get_home_dir() / "cache" / "mcp"


def get_hub_auth_path() -> Path:
    return get_home_dir() / "hub-auth.json"
