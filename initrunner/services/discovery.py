"""Role discovery, validation, and default directory helpers."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

_logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from initrunner.agent.schema.role import RoleDefinition


@dataclass
class DiscoveredRole:
    """A role YAML file discovered on disk."""

    path: Path
    role: RoleDefinition | None = None
    error: str | None = None


_SKIP_DIRS = frozenset(
    {
        "node_modules",
        ".venv",
        "venv",
        "__pycache__",
        ".git",
        ".tox",
        ".mypy_cache",
        ".ruff_cache",
        ".pytest_cache",
        "dist",
        "build",
        ".eggs",
        "_dashboard_static",
        ".hg",
        ".svn",
    }
)


def discover_roles_sync(dirs: list[Path]) -> list[DiscoveredRole]:
    """Scan directories for role YAML files (sync).

    Uses ``os.walk`` with directory pruning to skip common non-role
    directories (node_modules, .venv, .git, etc.) for fast scanning
    even from a large project root.
    """
    import yaml

    from initrunner.agent.loader import RoleLoadError, load_role

    results: list[DiscoveredRole] = []
    seen: set[Path] = set()

    for d in dirs:
        if not d.is_dir():
            continue
        for root, dirnames, filenames in os.walk(d):
            dirnames[:] = sorted(dn for dn in dirnames if dn not in _SKIP_DIRS)
            for fn in sorted(filenames):
                if not (fn.endswith(".yaml") or fn.endswith(".yml")):
                    continue
                p = Path(root) / fn
                resolved = p.resolve()
                if resolved in seen:
                    continue
                seen.add(resolved)

                # Quick check: is it an initrunner role file?
                try:
                    with open(p) as f:
                        raw = yaml.safe_load(f)
                    if not isinstance(raw, dict) or raw.get("apiVersion") != "initrunner/v1":
                        continue
                    if raw.get("kind") != "Agent":
                        continue
                except Exception as e:
                    _logger.debug("Skipping %s: %s", p, e)
                    continue

                try:
                    role = load_role(p)
                    results.append(DiscoveredRole(path=p, role=role))
                except RoleLoadError as e:
                    results.append(DiscoveredRole(path=p, error=str(e)))

    return results


def get_default_role_dirs(explicit_dir: Path | None = None) -> list[Path]:
    """Return directories to scan for role YAML files."""
    from initrunner.config import get_roles_dir

    dirs: list[Path] = []
    if explicit_dir is not None:
        dirs.append(explicit_dir)
    dirs.append(Path.cwd())
    examples = Path.cwd() / "examples" / "roles"
    if examples.is_dir():
        dirs.append(examples)
    global_roles = get_roles_dir()
    if global_roles.is_dir():
        dirs.append(global_roles)
    return dirs


def validate_role_sync(path: Path) -> DiscoveredRole:
    """Validate a single role file (sync)."""
    from initrunner.agent.loader import RoleLoadError, load_role

    try:
        role = load_role(path)
        return DiscoveredRole(path=path, role=role)
    except RoleLoadError as e:
        return DiscoveredRole(path=path, error=str(e))
