"""Auto-discovery of skills following agentskills.io progressive disclosure.

Scans well-known directories for SKILL.md files and exposes them to agents
via a lightweight catalog (Tier 1) and an ``activate_skill`` meta-tool
(Tier 2).  The model decides when to activate a skill based on the catalog
description -- no harness-side keyword matching.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from initrunner.agent.skills import SkillLoadError, _parse_frontmatter
from initrunner.services.discovery import _SKIP_DIRS

logger = logging.getLogger(__name__)

_MAX_RESOURCE_LISTING = 30
_RESOURCE_SKIP = frozenset({".git", "__pycache__", "node_modules", ".venv"})


@dataclass
class DiscoveredSkill:
    """A skill found via auto-discovery."""

    name: str
    description: str
    path: Path  # absolute path to SKILL.md
    scope: str  # "role-local" | "project" | "extra" | "user"


def discover_skills(
    role_dir: Path | None,
    extra_dirs: list[Path] | None,
    max_skills: int = 50,
    exclude_paths: set[Path] | None = None,
) -> list[DiscoveredSkill]:
    """Scan well-known directories for auto-discoverable skills.

    Returns up to *max_skills* skills, deduplicated by name (first-found wins,
    i.e. higher-priority scopes take precedence).
    """
    exclude = exclude_paths or set()
    seen_names: dict[str, str] = {}  # name -> scope that claimed it
    results: list[DiscoveredSkill] = []

    search: list[tuple[Path, str]] = []

    if role_dir is not None:
        search.append((role_dir / "skills", "role-local"))
        search.append((role_dir / ".agents" / "skills", "project"))

    if extra_dirs:
        for d in extra_dirs:
            search.append((d, "extra"))

    env_dir = os.environ.get("INITRUNNER_SKILL_DIR")
    if env_dir:
        search.append((Path(env_dir), "extra"))

    search.append((Path.home() / ".agents" / "skills", "user"))

    from initrunner.config import get_skills_dir

    search.append((get_skills_dir(), "user"))

    for base, scope in search:
        if not base.is_dir():
            continue
        if len(results) >= max_skills:
            break
        for item in sorted(base.iterdir()):
            if not item.is_dir():
                continue
            if item.name in _SKIP_DIRS:
                continue
            skill_md = item / "SKILL.md"
            if not skill_md.is_file():
                continue
            resolved = skill_md.resolve()
            if resolved in exclude:
                continue

            skill = _try_load_catalog_entry(skill_md, scope)
            if skill is None:
                continue

            if skill.name in seen_names:
                prev_scope = seen_names[skill.name]
                logger.warning(
                    "Auto-skill '%s' from %s (%s) shadowed by %s",
                    skill.name,
                    scope,
                    skill_md,
                    prev_scope,
                )
                continue

            seen_names[skill.name] = scope
            results.append(skill)
            if len(results) >= max_skills:
                break

    return results


def _try_load_catalog_entry(path: Path, scope: str) -> DiscoveredSkill | None:
    """Parse a SKILL.md just enough to extract name + description."""
    try:
        content = path.read_text()
    except OSError:
        logger.debug("Cannot read %s, skipping", path)
        return None

    try:
        data, _ = _parse_frontmatter(content)
    except (SkillLoadError, Exception):
        logger.debug("Unparseable frontmatter in %s, skipping", path)
        return None

    # Try full validation first, fall back to just name + description
    name, description = _extract_name_description(data, path)
    if not name or not description:
        return None

    return DiscoveredSkill(
        name=name,
        description=description,
        path=path.resolve(),
        scope=scope,
    )


def _extract_name_description(data: dict[str, Any], path: Path) -> tuple[str | None, str | None]:
    """Extract name and description from frontmatter, leniently."""
    from initrunner.agent.schema.role import SkillFrontmatter

    try:
        fm = SkillFrontmatter.model_validate(data)
        return fm.name, fm.description
    except ValidationError:
        pass

    # Lenient fallback: just need name + description
    name = data.get("name")
    description = data.get("description")

    if not name or not isinstance(name, str):
        logger.debug("Skill at %s has no valid name, skipping", path)
        return None, None
    if not description or not isinstance(description, str):
        logger.debug("Skill at %s has no description, skipping", path)
        return None, None

    logger.warning(
        "Skill '%s' at %s has frontmatter issues (loaded with name+description only)",
        name,
        path,
    )
    return name, description


def build_catalog_prompt(skills: list[DiscoveredSkill]) -> str:
    """Build the Tier 1 catalog for the system prompt."""
    lines = [
        "## Available Skills",
        "",
        "The following skills provide specialized instructions for specific tasks.",
        "When a task matches a skill's description, call the `activate_skill` tool",
        "with the skill's name to load its full instructions.",
        "",
        "<available_skills>",
    ]
    for s in skills:
        lines.append(f'<skill name="{s.name}">{s.description}</skill>')
    lines.append("</available_skills>")
    return "\n".join(lines)


def build_activate_skill_toolset(
    skills: list[DiscoveredSkill],
    activated_names: set[str],
):
    """Build a ``FunctionToolset`` containing the ``activate_skill`` meta-tool."""
    from pydantic_ai.toolsets.function import FunctionToolset

    skill_map = {s.name: s for s in skills}
    toolset = FunctionToolset()

    @toolset.tool
    def activate_skill(name: str) -> str:
        """Load full instructions for a discovered skill.

        Call this when a task matches a skill's description in your
        available_skills catalog.

        Args:
            name: The skill name from the available_skills catalog.
        """
        skill = skill_map.get(name)
        if skill is None:
            return f"Unknown skill '{name}'. Check available_skills."
        if name in activated_names:
            return f"Skill '{name}' is already active in this session."
        activated_names.add(name)

        try:
            content = skill.path.read_text()
        except OSError as e:
            return f"Failed to read skill '{name}': {e}"

        try:
            _, body = _parse_frontmatter(content)
        except (SkillLoadError, Exception):
            return f"Failed to parse skill '{name}'."

        resources = _list_resources(skill.path.parent)

        parts = [f'<skill_content name="{name}">', body.strip()]
        if resources:
            parts.append("\n<skill_resources>")
            for r in resources:
                parts.append(f"  <file>{r}</file>")
            parts.append("</skill_resources>")
        parts.append("</skill_content>")
        return "\n".join(parts)

    return toolset


def _list_resources(skill_dir: Path) -> list[str]:
    """List relative paths of files in *skill_dir*, excluding SKILL.md."""
    files: list[str] = []
    try:
        items = sorted(skill_dir.rglob("*"))
    except OSError:
        return files
    for item in items:
        if item.is_file() and item.name != "SKILL.md":
            if any(skip in item.parts for skip in _RESOURCE_SKIP):
                continue
            files.append(str(item.relative_to(skill_dir)))
            if len(files) >= _MAX_RESOURCE_LISTING:
                break
    return files
