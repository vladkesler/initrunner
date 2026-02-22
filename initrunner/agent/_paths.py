"""Shared path validation for tools and stores."""

from __future__ import annotations

from pathlib import Path

from initrunner.config import get_home_dir


def _get_initrunner_dir() -> Path:
    """Return the InitRunner home directory (not cached at module level)."""
    return get_home_dir()


def validate_path_within(
    target: Path,
    allowed_roots: list[Path],
    *,
    allowed_ext: set[str] | None = None,
    reject_symlinks: bool = False,
) -> tuple[str | None, Path]:
    """Return ``(error, resolved_path)``.  Error is ``None`` on success.

    Callers should use the returned *resolved_path* for all subsequent I/O
    to avoid TOCTOU races between validation and use.
    """
    if reject_symlinks:
        curr = target
        while curr != curr.parent:
            if curr.is_symlink():
                return f"Error: path component '{curr}' is a symlink", target
            curr = curr.parent

    resolved = target.resolve()
    for root in allowed_roots:
        try:
            resolved.relative_to(root.resolve())
            break
        except ValueError:
            continue
    else:
        return f"Error: path '{target}' is outside allowed directories", resolved

    if allowed_ext and target.suffix not in allowed_ext:
        return f"Error: file type {target.suffix} is not allowed", resolved
    return None, resolved
