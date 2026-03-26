"""Skill discovery, validation, and management for the dashboard.

Path-based inventory (no name deduplication) that supports both
directory-form (``skills/name/SKILL.md``) and flat-form (``skills/name.md``)
skills.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

from initrunner.agent.skills import (
    RequirementStatus,
    SkillLoadError,
    _parse_frontmatter,
    _resolve_skill_path,
    check_requirements,
    load_skill,
)

logger = logging.getLogger(__name__)

_SKIP_DIRS = frozenset(
    {
        ".git",
        "__pycache__",
        "node_modules",
        ".venv",
        "venv",
        "dist",
        "build",
        ".eggs",
        ".mypy_cache",
        ".ruff_cache",
        ".pytest_cache",
    }
)


@dataclass
class DiscoveredSkillFull:
    """Rich skill discovery result for the dashboard."""

    name: str
    description: str
    path: Path  # absolute resolved path to SKILL.md or name.md
    scope: str  # "role-local" | "project" | "extra" | "user"
    is_directory_form: bool  # True = dir/SKILL.md, False = flat name.md
    frontmatter: object | None = None  # SkillFrontmatter when parsed
    prompt: str = ""
    requirement_statuses: list[RequirementStatus] = field(default_factory=list)
    has_resources: bool = False
    error: str | None = None


@dataclass
class ValidationIssue:
    field: str
    message: str
    severity: str  # "error" | "warning"


class SkillDeleteBlockedError(Exception):
    """Raised when a directory-form skill has resource files blocking delete."""

    def __init__(self, resource_files: list[str]) -> None:
        self.resource_files = resource_files
        super().__init__(
            f"Cannot delete: skill directory contains {len(resource_files)} "
            f"resource file(s): {', '.join(resource_files[:5])}"
        )


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def _build_search_paths(role_dirs: list[Path]) -> list[tuple[Path, str]]:
    """Build the ordered search path list for skill discovery.

    Scans:
    1. Shared skill dirs (``<role_dir>/skills/``, ``<role_dir>/.agents/skills/``)
    2. Role-local skill dirs (``<role_dir>/<role_name>/skills/`` for each
       discovered role directory that contains a ``skills/`` subdirectory)
    3. Extra dirs from ``INITRUNNER_SKILL_DIR``
    4. User-level dirs (``~/.agents/skills/``, ``~/.initrunner/skills/``)
    """
    search: list[tuple[Path, str]] = []

    for rd in role_dirs:
        # Shared skills
        search.append((rd / "skills", "role-local"))
        search.append((rd / ".agents" / "skills", "project"))

        # Role-local skills: scan role subdirectories for skills/ dirs
        if rd.is_dir():
            try:
                for item in sorted(rd.iterdir()):
                    if not item.is_dir() or item.name in _SKIP_DIRS:
                        continue
                    role_skills = item / "skills"
                    if role_skills.is_dir():
                        search.append((role_skills, "role-local"))
            except OSError:
                pass

    env_dir = os.environ.get("INITRUNNER_SKILL_DIR")
    if env_dir:
        for part in env_dir.split(os.pathsep):
            p = Path(part)
            if p.is_dir():
                search.append((p, "extra"))

    search.append((Path.home() / ".agents" / "skills", "user"))

    from initrunner.config import get_skills_dir

    search.append((get_skills_dir(), "user"))

    return search


def _list_skill_resources(skill_dir: Path) -> list[str]:
    """List relative paths of sibling files in a skill directory (excl. SKILL.md)."""
    from initrunner.agent.auto_skills import _list_resources

    return _list_resources(skill_dir)


def _load_skill_at_path(
    path: Path,
    scope: str,
    is_directory_form: bool,
) -> DiscoveredSkillFull:
    """Load a single skill file, returning an error result on failure."""
    resolved = path.resolve()
    try:
        skill_def = load_skill(resolved)
        statuses = check_requirements(skill_def)
        has_resources = False
        if is_directory_form:
            has_resources = len(_list_skill_resources(resolved.parent)) > 0
        return DiscoveredSkillFull(
            name=skill_def.frontmatter.name,
            description=skill_def.frontmatter.description,
            path=resolved,
            scope=scope,
            is_directory_form=is_directory_form,
            frontmatter=skill_def.frontmatter,
            prompt=skill_def.prompt,
            requirement_statuses=statuses,
            has_resources=has_resources,
        )
    except (SkillLoadError, Exception) as exc:
        # Try lenient name extraction for broken skills
        name, description = _lenient_extract(resolved)
        return DiscoveredSkillFull(
            name=name or resolved.stem,
            description=description or "",
            path=resolved,
            scope=scope,
            is_directory_form=is_directory_form,
            error=str(exc),
        )


def _lenient_extract(path: Path) -> tuple[str | None, str | None]:
    """Extract name and description from a skill even if validation fails."""
    try:
        content = path.read_text()
        data, _ = _parse_frontmatter(content)
        name = data.get("name")
        desc = data.get("description")
        if isinstance(name, str) and isinstance(desc, str):
            return name, desc
    except Exception:
        pass
    return None, None


def discover_skills_full(
    role_dirs: list[Path],
    max_skills: int = 200,
) -> list[DiscoveredSkillFull]:
    """Scan all skill directories for both directory-form and flat-form skills.

    Path-based deduplication only (no name-based dedup). Skills with the same
    name in different scopes are all returned.
    """
    search = _build_search_paths(role_dirs)
    seen_paths: set[Path] = set()
    results: list[DiscoveredSkillFull] = []

    for base, scope in search:
        if not base.is_dir():
            continue
        if len(results) >= max_skills:
            break

        try:
            items = sorted(base.iterdir())
        except OSError:
            continue

        for item in items:
            if len(results) >= max_skills:
                break

            # Directory-form: item/SKILL.md
            if item.is_dir():
                if item.name in _SKIP_DIRS:
                    continue
                skill_md = item / "SKILL.md"
                if not skill_md.is_file():
                    continue
                resolved = skill_md.resolve()
                if resolved in seen_paths:
                    continue
                seen_paths.add(resolved)
                results.append(_load_skill_at_path(resolved, scope, is_directory_form=True))

            # Flat-form: item is a .md file (not SKILL.md at root)
            elif item.is_file() and item.suffix == ".md" and item.name != "SKILL.md":
                resolved = item.resolve()
                if resolved in seen_paths:
                    continue
                seen_paths.add(resolved)
                results.append(_load_skill_at_path(resolved, scope, is_directory_form=False))

    return results


# ---------------------------------------------------------------------------
# Single-file operations
# ---------------------------------------------------------------------------


def load_skill_full(path: Path) -> DiscoveredSkillFull:
    """Load a single skill file with full validation.

    Broken skills get ``error`` set rather than raising, so they remain
    visible in the dashboard for editing.
    """
    resolved = path.resolve()
    is_dir_form = resolved.name == "SKILL.md"
    # Scope is unknown when loading a single file; caller can override
    return _load_skill_at_path(resolved, scope="unknown", is_directory_form=is_dir_form)


def validate_skill_content(content: str) -> list[ValidationIssue]:
    """Validate SKILL.md content (frontmatter + body).

    Returns a list of validation issues. Issues with severity ``"error"``
    should block persistence.
    """
    from pydantic import ValidationError

    from initrunner.agent.schema.role import SkillFrontmatter

    issues: list[ValidationIssue] = []

    # Parse frontmatter
    try:
        data, _body = _parse_frontmatter(content)
    except SkillLoadError as exc:
        issues.append(ValidationIssue(field="frontmatter", message=str(exc), severity="error"))
        return issues
    except Exception as exc:
        issues.append(
            ValidationIssue(field="frontmatter", message=f"Parse error: {exc}", severity="error")
        )
        return issues

    # Validate against schema
    try:
        fm = SkillFrontmatter.model_validate(data)
    except ValidationError as exc:
        for err in exc.errors():
            loc = ".".join(str(x) for x in err["loc"])
            issues.append(
                ValidationIssue(field=loc or "frontmatter", message=err["msg"], severity="error")
            )
        return issues

    # Warnings
    if not _body.strip():
        issues.append(
            ValidationIssue(
                field="prompt",
                message="Skill has no prompt body. Consider adding usage guidelines.",
                severity="warning",
            )
        )

    if not fm.tools and not _body.strip():
        issues.append(
            ValidationIssue(
                field="tools",
                message="Skill provides neither tools nor methodology prompt.",
                severity="warning",
            )
        )

    return issues


def create_skill(name: str, directory: Path, provider: str = "openai") -> Path:
    """Scaffold a new skill in directory format. Returns path to SKILL.md."""
    from initrunner.templates import template_skill

    skill_dir = directory / name
    skill_file = skill_dir / "SKILL.md"

    if skill_dir.exists():
        raise SkillLoadError(f"Directory already exists: {skill_dir}")

    skill_dir.mkdir(parents=True)
    content = template_skill(name, provider)
    skill_file.write_text(content)
    return skill_file.resolve()


def save_skill_content(path: Path, content: str) -> tuple[bool, list[str]]:
    """Validate then save skill content. Returns (valid, issue_strings).

    If validation produces errors, content is NOT written to disk.
    """
    issues = validate_skill_content(content)
    errors = [f"{i.field}: {i.message}" for i in issues if i.severity == "error"]
    warnings = [f"{i.field}: {i.message}" for i in issues if i.severity == "warning"]

    if errors:
        return False, errors

    path.write_text(content)
    return True, warnings


def delete_skill(path: Path) -> None:
    """Delete a skill file. For directory-form, blocks if resource files exist."""
    resolved = path.resolve()

    if not resolved.is_file():
        raise SkillLoadError(f"Skill file not found: {resolved}")

    is_dir_form = resolved.name == "SKILL.md"

    if is_dir_form:
        resources = _list_skill_resources(resolved.parent)
        if resources:
            raise SkillDeleteBlockedError(resources)
        # Remove SKILL.md then empty parent
        resolved.unlink()
        try:
            resolved.parent.rmdir()
        except OSError:
            pass  # parent not empty (race or hidden files)
    else:
        resolved.unlink()


# ---------------------------------------------------------------------------
# Directory listing (for create targets)
# ---------------------------------------------------------------------------


def get_skill_directories(role_dirs: list[Path]) -> list[str]:
    """Return valid directories where new skills can be created."""
    candidates: list[Path] = []

    for rd in role_dirs:
        candidates.append(rd / "skills")
        candidates.append(rd / ".agents" / "skills")

    env_dir = os.environ.get("INITRUNNER_SKILL_DIR")
    if env_dir:
        for part in env_dir.split(os.pathsep):
            candidates.append(Path(part))

    candidates.append(Path.home() / ".agents" / "skills")

    from initrunner.config import get_skills_dir

    candidates.append(get_skills_dir())

    # Return dirs that exist or whose parent exists (can be created)
    seen: set[str] = set()
    result: list[str] = []
    for c in candidates:
        s = str(c)
        if s in seen:
            continue
        seen.add(s)
        if c.is_dir() or c.parent.is_dir():
            result.append(s)
    return result


# ---------------------------------------------------------------------------
# Agent cross-referencing
# ---------------------------------------------------------------------------


def resolve_agent_skill_refs(
    spec_skills: list[str],
    role_dir: Path,
    extra_dirs: list[Path] | None,
) -> list[Path]:
    """Resolve agent skill refs to absolute paths using runtime resolution logic.

    Silently skips unresolvable refs (returns only the ones that resolve).
    """
    resolved: list[Path] = []
    for ref in spec_skills:
        try:
            path = _resolve_skill_path(ref, role_dir, extra_dirs)
            resolved.append(path)
        except SkillLoadError:
            logger.debug("Could not resolve skill ref '%s' from %s", ref, role_dir)
    return resolved
