"""Shared secure-path helpers for ~/.initrunner/ directory tree."""

from __future__ import annotations

import sys
from pathlib import Path


def ensure_private_dir(path: Path) -> None:
    """Create (or tighten) a directory to mode 0o700."""
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if sys.platform != "win32":
        path.chmod(0o700)


def secure_database(db_path: Path) -> None:
    """chmod an existing database file to 0o600 (owner-only)."""
    if sys.platform != "win32" and db_path.exists():
        db_path.chmod(0o600)
