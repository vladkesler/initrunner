"""Path-validation helpers for dashboard save endpoints.

Builder endpoints accept a target *directory* and *filename* from the request
body. These helpers confine writes to the configured role/skill directories,
rejecting absolute escapes and ``..`` traversal.

The containment check mirrors the pattern already used in ``ingest.py``: resolve
the full destination path *after* joining the request-supplied segment, then
verify it is relative to an allowed root. Containment is the only test -- an
absolute *directory* is permitted as long as it resolves within a root, because
the UI offers absolute save dirs.
"""

from __future__ import annotations

from pathlib import Path


class PathValidationError(ValueError):
    """Raised when a requested write target escapes the allowed roots."""


def safe_basename(name: str) -> str:
    """Return the bare filename, rejecting separators and traversal.

    Raises :class:`PathValidationError` if *name* is empty or differs from
    ``Path(name).name`` (i.e. it contained a path separator or ``..``).
    """
    base = Path(name).name
    if not base or base != name or base in (".", ".."):
        raise PathValidationError(f"Invalid name: {name!r}")
    return base


def _within(path: Path, allowed_roots: list[Path]) -> bool:
    resolved = path.resolve()
    return any(resolved.is_relative_to(root.resolve()) for root in allowed_roots)


def _validated_join(directory: str, segment: str, allowed_roots: list[Path]) -> Path:
    base = safe_basename(segment)
    target_dir = Path(directory).resolve()
    if not _within(target_dir, allowed_roots):
        raise PathValidationError(
            f"Directory {directory!r} is not within an allowed root: "
            f"{[str(r) for r in allowed_roots]}"
        )
    dest = (target_dir / base).resolve()
    if not _within(dest, allowed_roots):
        raise PathValidationError(f"Resolved path escapes allowed roots: {dest}")
    return dest


def validated_file_target(directory: str, filename: str, allowed_roots: list[Path]) -> Path:
    """Resolve *directory*/*filename* and confirm it stays within an allowed root.

    Returns the validated destination *file* path. Raises
    :class:`PathValidationError` on any escape.
    """
    return _validated_join(directory, filename, allowed_roots)


def validated_child_dir(directory: str, child: str, allowed_roots: list[Path]) -> Path:
    """Resolve *directory*/*child* as a project subdirectory within an allowed root.

    Returns the validated destination *directory* path. Raises
    :class:`PathValidationError` on any escape.
    """
    return _validated_join(directory, child, allowed_roots)


def role_save_roots(settings) -> list[Path]:
    """Allowed roots for role/team/flow saves.

    The configured role dirs plus the global ``~/.initrunner/roles`` -- the
    latter is offered by the builder UI as a save dir even before discovery has
    seen it (it is created on first run), so it must be permitted here too.
    Mirrors the allowlist construction in ``builder.py``'s ``save_agent``.
    """
    from initrunner.config import get_roles_dir

    roots = list(settings.get_role_dirs())
    global_roles = get_roles_dir()
    if global_roles not in roots:
        roots.append(global_roles)
    return roots
