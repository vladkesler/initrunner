"""Shared secure-path helpers and lazy path wrappers for ~/.initrunner/ directory tree."""

from __future__ import annotations

import sys
from pathlib import Path


class LazyPath:
    """Lazy-evaluated Path wrapper — subclasses implement ``_resolve``."""

    def _resolve(self) -> Path:
        raise NotImplementedError

    def __fspath__(self) -> str:
        return str(self._resolve())

    def __str__(self) -> str:
        return str(self._resolve())

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self._resolve()!r})"

    def __truediv__(self, other: str) -> Path:
        return self._resolve() / other

    def __getattr__(self, name: str):
        return getattr(self._resolve(), name)


def ensure_private_dir(path: Path) -> None:
    """Create (or tighten) a directory to mode 0o700."""
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if sys.platform != "win32":
        path.chmod(0o700)


def secure_database(db_path: Path) -> None:
    """chmod an existing database file to 0o600 (owner-only)."""
    if sys.platform != "win32" and db_path.exists():
        db_path.chmod(0o600)
