"""Shared secure-path helpers and lazy path wrappers for ~/.initrunner/ directory tree."""

from __future__ import annotations

import os
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
    """Create a directory and, when we own it, tighten it to mode 0o700.

    The path may be one we do not own, for example a shared parent such as
    ``/tmp`` passed via ``--audit-db`` or a store path. Locking down such a
    directory is not ours to do and would raise ``PermissionError``, so
    permissions are only adjusted on a directory we just created or already own.
    Privacy of the data itself is enforced at the file level (see
    :func:`secure_database`, mode 0o600).
    """
    newly_created = not path.exists()
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if sys.platform == "win32":
        return
    if not (newly_created or _owned_by_current_user(path)):
        return
    try:
        path.chmod(0o700)
    except OSError:
        # A directory we cannot lock down still holds only 0o600 data files,
        # so audit and store contents stay owner-only regardless.
        pass


def _owned_by_current_user(path: Path) -> bool:
    """Return True if ``path`` is owned by the current user (POSIX, best effort)."""
    try:
        return path.stat().st_uid == os.getuid()
    except (OSError, AttributeError):
        return False


def secure_database(db_path: Path) -> None:
    """chmod an existing database file to 0o600 (owner-only)."""
    if sys.platform != "win32" and db_path.exists():
        db_path.chmod(0o600)
