"""Load, resolve, and merge reusable SKILL.md bundles."""

from __future__ import annotations

import logging
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from initrunner.agent.schema.role import SkillDefinition, SkillFrontmatter
from initrunner.agent.schema.tools import ToolConfig

logger = logging.getLogger(__name__)


class SkillLoadError(Exception):
    """Raised when a skill definition cannot be loaded or validated."""


@dataclass
class RequirementStatus:
    name: str
    kind: str  # "bin" or "env"
    met: bool
    detail: str


@dataclass
class ResolvedSkill:
    definition: SkillDefinition
    source_path: Path
    requirement_statuses: list[RequirementStatus] = field(default_factory=list)


def _parse_frontmatter(content: str) -> tuple[dict[str, Any], str]:
    """Split a SKILL.md into YAML frontmatter dict and Markdown body."""
    if not content.startswith("---"):
        raise SkillLoadError("SKILL.md must start with '---' frontmatter delimiter")

    # Find closing delimiter
    end_idx = content.index("\n") + 1  # skip first ---
    closing = content.find("---", end_idx)
    if closing == -1:
        raise SkillLoadError("Missing closing '---' frontmatter delimiter")

    # Ensure closing --- is at the start of a line
    if closing > 0 and content[closing - 1] != "\n":
        raise SkillLoadError("Missing closing '---' frontmatter delimiter")

    frontmatter_raw = content[end_idx:closing]
    body = content[closing + 3 :].lstrip("\n")

    try:
        data = yaml.safe_load(frontmatter_raw)
    except yaml.YAMLError as e:
        raise SkillLoadError(f"Invalid YAML in frontmatter: {e}") from e

    if not isinstance(data, dict):
        raise SkillLoadError(f"Frontmatter must be a YAML mapping, got {type(data).__name__}")

    return data, body


def load_skill(path: Path) -> SkillDefinition:
    """Read a SKILL.md file and return a validated SkillDefinition."""
    try:
        content = path.read_text()
    except OSError as e:
        raise SkillLoadError(f"Cannot read {path}: {e}") from e

    try:
        data, body = _parse_frontmatter(content)
    except SkillLoadError:
        raise
    except Exception as e:
        raise SkillLoadError(f"Failed to parse {path}: {e}") from e

    try:
        frontmatter = SkillFrontmatter.model_validate(data)
    except ValidationError as e:
        raise SkillLoadError(f"Validation failed for {path}:\n{e}") from e

    if not frontmatter.tools:
        logger.warning(
            "Skill '%s' has no tool configs"
            " (may be a community skill without InitRunner extensions)",
            frontmatter.name,
        )

    return SkillDefinition(frontmatter=frontmatter, prompt=body)


def _resolve_skill_path(
    ref: str,
    role_dir: Path | None,
    extra_dirs: list[Path] | None,
) -> Path:
    """Resolve a skill reference to a concrete file path."""
    searched: list[str] = []

    # Explicit path (contains '/' or ends with '.md')
    if "/" in ref or ref.endswith(".md"):
        base = role_dir or Path(".")
        candidate = base / ref

        if ref.endswith(".md"):
            resolved = candidate.resolve()
            if resolved.is_file():
                return resolved
            searched.append(str(resolved))
        else:
            # Directory reference
            skill_md = candidate / "SKILL.md"
            if skill_md.is_file():
                return skill_md.resolve()
            searched.append(str(skill_md))

            # Try as .md file
            md_path = Path(str(candidate) + ".md")
            if md_path.is_file():
                return md_path.resolve()
            searched.append(str(md_path))

        raise SkillLoadError(
            f"Skill not found for '{ref}'. Searched:\n" + "\n".join(f"  - {s}" for s in searched)
        )

    # Bare name lookup
    name = ref
    search_dirs: list[Path] = []

    if role_dir is not None:
        search_dirs.append(role_dir / "skills")

    if extra_dirs:
        search_dirs.extend(extra_dirs)

    from initrunner.config import get_skills_dir

    search_dirs.append(get_skills_dir())

    for d in search_dirs:
        # Directory format: {dir}/{name}/SKILL.md
        candidate = d / name / "SKILL.md"
        if candidate.is_file():
            return candidate.resolve()
        searched.append(str(candidate))

        # Flat format: {dir}/{name}.md
        candidate = d / f"{name}.md"
        if candidate.is_file():
            return candidate.resolve()
        searched.append(str(candidate))

    raise SkillLoadError(
        f"Skill '{name}' not found. Searched:\n"
        + "\n".join(f"  - {s}" for s in searched)
        + f"\n\nHint: use a relative path (e.g. ../skills/{name})"
        " or pass --skill-dir to add a search directory."
    )


def check_requirements(skill: SkillDefinition) -> list[RequirementStatus]:
    """Check if a skill's external requirements are met."""
    statuses: list[RequirementStatus] = []

    for env_var in skill.frontmatter.requires.env:
        met = env_var in os.environ
        detail = "" if met else f"environment variable '{env_var}' is not set"
        statuses.append(RequirementStatus(name=env_var, kind="env", met=met, detail=detail))

    for bin_name in skill.frontmatter.requires.bins:
        met = shutil.which(bin_name) is not None
        detail = "" if met else f"binary '{bin_name}' not found on PATH"
        statuses.append(RequirementStatus(name=bin_name, kind="bin", met=met, detail=detail))

    return statuses


def resolve_skills(
    refs: list[str],
    role_dir: Path | None,
    extra_dirs: list[Path] | None,
) -> list[ResolvedSkill]:
    """Resolve, load, deduplicate, and check requirements for skill references."""
    seen_paths: dict[Path, int] = {}
    result: list[ResolvedSkill] = []

    for ref in refs:
        path = _resolve_skill_path(ref, role_dir, extra_dirs)

        if path in seen_paths:
            logger.debug(
                "Skipping duplicate skill reference '%s' (already loaded from %s)", ref, path
            )
            continue

        skill_def = load_skill(path)
        statuses = check_requirements(skill_def)
        seen_paths[path] = len(result)
        result.append(
            ResolvedSkill(definition=skill_def, source_path=path, requirement_statuses=statuses)
        )

    return result


def merge_skill_tools(
    skills: list[ResolvedSkill],
    role_tools: list[ToolConfig],
) -> list[ToolConfig]:
    """Merge skill tools with role tools, deduplicating by tool type.

    Later skills override earlier skills for the same type.
    Role tools override skill tools of the same type.
    """
    merged: dict[str, ToolConfig] = {}
    source: dict[str, str] = {}  # type → source name for logging

    # Skill tools first (in declaration order)
    for rs in skills:
        skill_name = rs.definition.frontmatter.name
        for tool in rs.definition.frontmatter.tools:
            tool_type = tool.type
            if tool_type in merged:
                logger.warning(
                    "Tool type '%s' from skill '%s' overrides same type from skill '%s'",
                    tool_type,
                    skill_name,
                    source[tool_type],
                )
            merged[tool_type] = tool
            source[tool_type] = skill_name

    # Role tools last (override skills)
    for tool in role_tools:
        tool_type = tool.type
        if tool_type in source:
            logger.warning(
                "Tool type '%s' in role overrides same type from skill '%s'",
                tool_type,
                source[tool_type],
            )
        merged[tool_type] = tool

    return list(merged.values())


def build_skill_system_prompt(skills: list[ResolvedSkill]) -> str:
    """Build a structured system prompt section from resolved skills."""
    sections: list[str] = []

    for rs in skills:
        prompt = rs.definition.prompt.strip()
        if not prompt:
            continue
        name = rs.definition.frontmatter.name
        sections.append(f"### Skill: {name}\n{prompt}")

    if not sections:
        return ""

    header = (
        "## Skills\n\n"
        "The following skills provide you with additional capabilities.\n"
        "Follow their usage guidelines when performing relevant tasks."
    )
    return header + "\n\n" + "\n\n".join(sections)
