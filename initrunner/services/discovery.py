"""Role, flow, and team discovery, validation, and default directory helpers."""

from __future__ import annotations

import logging
import os
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, TypeVar

from initrunner._constants import SKIP_DIRS

_logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from initrunner.agent.schema.role import RoleDefinition
    from initrunner.flow.schema import FlowDefinition
    from initrunner.team.schema import TeamDefinition


@dataclass
class DiscoveredRole:
    """A role YAML file discovered on disk."""

    path: Path
    role: RoleDefinition | None = None
    error: str | None = None


@dataclass
class DiscoveredFlow:
    """A flow YAML file discovered on disk."""

    path: Path
    flow: FlowDefinition | None = None
    error: str | None = None


@dataclass
class DiscoveredTeam:
    """A team YAML file discovered on disk."""

    path: Path
    team: TeamDefinition | None = None
    error: str | None = None


# Backwards-compatible alias for external importers (auto_skills.py).
_SKIP_DIRS = SKIP_DIRS


_INITRUNNER_API_VERSIONS = {"initrunner/v1"}
_INITRUNNER_KINDS = {"Agent", "Team", "Flow"}


def project_marker(directory: Path) -> Path | None:
    """Return the directory's designated role file, when it has one.

    ``agent.yaml`` or ``role.yaml`` names the one agent a directory is about,
    and it wins over anything else in the directory.
    """
    for default_name in ("agent.yaml", "role.yaml"):
        default = directory / default_name
        if default.is_file():
            return default
    return None


def _top_level_yaml(directory: Path) -> list[Path]:
    """Every ``*.yaml`` / ``*.yml`` file directly inside *directory*, sorted."""
    files = [f for ext in ("*.yaml", "*.yml") for f in directory.glob(ext) if f.is_file()]
    return sorted(files)


def top_level_documents(directory: Path) -> list[Path]:
    """Return the InitRunner documents directly inside *directory*, sorted.

    Deliberately not recursive. Nested directories hold the parts other
    documents are built from -- a team's personas, a flow's steps -- and those
    are not standalone agents someone meant to run.

    Files that are not YAML mappings, or not recognisable InitRunner documents,
    are skipped rather than reported: a directory is allowed to contain other
    YAML. See :func:`unreadable_yaml_files` for the files this could not even
    parse, which a caller treating the directory as a group should report.
    """
    import yaml

    from initrunner.agent.schema.document import DocumentClass, classify_mapping

    documents: list[Path] = []
    for f in _top_level_yaml(directory):
        try:
            with open(f) as fh:
                data = yaml.safe_load(fh)
            if not isinstance(data, dict):
                continue
            classification = classify_mapping(data)
            if classification.document_class in {
                DocumentClass.FLAT_AGENT,
                DocumentClass.ENVELOPE_AGENT,
                DocumentClass.ENVELOPE_TEAM,
                DocumentClass.ENVELOPE_FLOW,
            }:
                documents.append(f)
            elif (
                data.get("apiVersion") in _INITRUNNER_API_VERSIONS
                and data.get("kind") in _INITRUNNER_KINDS
            ):
                documents.append(f)
        except Exception:
            continue

    return documents


def unreadable_yaml_files(directory: Path) -> list[tuple[Path, str]]:
    """Top-level YAML files that could not be parsed at all, with the reason.

    A file whose contents do not parse cannot be classified, so
    :func:`top_level_documents` cannot see it. Somewhere that would silently
    drop an agent -- serving a directory as a group -- the caller reports these
    instead.
    """
    import yaml

    broken: list[tuple[Path, str]] = []
    for f in _top_level_yaml(directory):
        try:
            with open(f) as fh:
                yaml.safe_load(fh)
        except (yaml.YAMLError, OSError, UnicodeDecodeError) as e:
            broken.append((f, str(e).replace("\n", " ")))
    return broken


def _scan_yaml_kind(dirs: list[Path], kind: str) -> Iterator[Path]:
    """Yield paths to YAML files matching ``apiVersion: initrunner/v1`` and the given kind.

    Uses ``os.walk`` with directory pruning to skip common non-source
    directories for fast scanning even from a large project root.
    """
    import yaml

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

                try:
                    with open(p) as f:
                        raw = yaml.safe_load(f)
                    if not isinstance(raw, dict):
                        continue
                    from initrunner.agent.schema.adapt import run_kind_from_mapping
                    from initrunner.agent.schema.document import (
                        DocumentClass,
                        classify_mapping,
                    )

                    classification = classify_mapping(raw)
                    if classification.document_class is DocumentClass.FLAT_AGENT:
                        if run_kind_from_mapping(raw) != kind:
                            continue
                    elif raw.get("apiVersion") != "initrunner/v1" or raw.get("kind") != kind:
                        continue
                except Exception as e:
                    _logger.debug("Skipping %s: %s", p, e)
                    continue

                yield p


_D = TypeVar("_D")


def _discover_sync(
    dirs: list[Path],
    kind: str,
    loader: Callable[[Path], object],
    error_classes: tuple[type[Exception], ...],
    make_success: Callable[[Path, object], _D],
    make_error: Callable[[Path, str], _D],
) -> list[_D]:
    """Generic discovery: scan for YAML files of *kind*, load each, collect results."""
    results: list[_D] = []
    for p in _scan_yaml_kind(dirs, kind):
        try:
            obj = loader(p)
            results.append(make_success(p, obj))
        except error_classes as e:
            results.append(make_error(p, str(e)))
        except Exception as e:
            results.append(make_error(p, str(e)))
    return results


def discover_roles_sync(dirs: list[Path]) -> list[DiscoveredRole]:
    """Scan directories for role YAML files (sync)."""
    from initrunner.agent.loader import RoleLoadError, load_role

    return _discover_sync(
        dirs,
        "Agent",
        load_role,
        (RoleLoadError,),
        lambda p, r: DiscoveredRole(path=p, role=r),
        lambda p, e: DiscoveredRole(path=p, error=e),
    )


def discover_flows_sync(dirs: list[Path]) -> list[DiscoveredFlow]:
    """Scan directories for flow YAML files (sync)."""
    from initrunner.flow.loader import FlowLoadError, load_flow

    return _discover_sync(
        dirs,
        "Flow",
        load_flow,
        (FlowLoadError,),
        lambda p, c: DiscoveredFlow(path=p, flow=c),
        lambda p, e: DiscoveredFlow(path=p, error=e),
    )


def discover_teams_sync(dirs: list[Path]) -> list[DiscoveredTeam]:
    """Scan directories for team YAML files (sync)."""
    from initrunner.team.loader import TeamLoadError, load_team

    return _discover_sync(
        dirs,
        "Team",
        load_team,
        (TeamLoadError,),
        lambda p, t: DiscoveredTeam(path=p, team=t),
        lambda p, e: DiscoveredTeam(path=p, error=e),
    )


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
    # Bundled starter examples shipped with the package
    starters = Path(__file__).resolve().parent.parent / "dashboard" / "_starters"
    if starters.is_dir():
        dirs.append(starters)
    return dirs


def load_role_sync(path: Path) -> RoleDefinition:
    """Load a single role file (sync). Raises RoleLoadError on failure."""
    from initrunner.agent.loader import load_role

    return load_role(path)


def validate_role_sync(path: Path) -> DiscoveredRole:
    """Validate a single role file (sync)."""
    from initrunner.agent.loader import RoleLoadError, load_role

    try:
        role = load_role(path)
        return DiscoveredRole(path=path, role=role)
    except RoleLoadError as e:
        return DiscoveredRole(path=path, error=str(e))
