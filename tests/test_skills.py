"""Tests for the skills system (SKILL.md loading, resolution, merging)."""

from __future__ import annotations

import logging
import textwrap
from pathlib import Path

import pytest
from pydantic import ValidationError

from initrunner.agent.schema.base import ModelConfig
from initrunner.agent.schema.role import (
    AgentSpec,
    RequiresConfig,
    SkillDefinition,
    SkillFrontmatter,
    parse_tool_list,
)
from initrunner.agent.schema.tools import (
    DateTimeToolConfig,
    FileSystemToolConfig,
    HttpToolConfig,
    WebReaderToolConfig,
)
from initrunner.agent.skills import (
    ResolvedSkill,
    SkillLoadError,
    _parse_frontmatter,
    _resolve_skill_path,
    build_skill_system_prompt,
    check_requirements,
    load_skill,
    merge_skill_tools,
    resolve_skills,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

MINIMAL_SKILL_MD = textwrap.dedent("""\
    ---
    name: test-skill
    description: A test skill
    ---

    Test prompt body.
""")

FULL_SKILL_MD = textwrap.dedent("""\
    ---
    name: web-researcher
    description: Web research tools
    license: MIT
    compatibility: Requires initrunner
    metadata:
      author: test
      version: "1.0"
    tools:
      - type: web_reader
        timeout_seconds: 10
      - type: http
        base_url: https://example.com
        allowed_methods: [GET]
    requires:
      env:
        - API_KEY
      bins:
        - curl
    ---

    You have web research capabilities.

    ## Guidelines

    - Be concise
""")


def _write_skill(tmp_path: Path, name: str, content: str) -> Path:
    """Write a SKILL.md inside a named directory."""
    skill_dir = tmp_path / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text(content)
    return skill_file


def _write_flat_skill(tmp_path: Path, name: str, content: str) -> Path:
    """Write a flat {name}.md skill file."""
    skill_file = tmp_path / f"{name}.md"
    skill_file.write_text(content)
    return skill_file


def _make_resolved_skill(
    name: str,
    tools: list | None = None,
    prompt: str = "Skill prompt.",
    source: Path | None = None,
) -> ResolvedSkill:
    fm = SkillFrontmatter(
        name=name,
        description=f"{name} description",
        tools=tools or [],
    )
    defn = SkillDefinition(frontmatter=fm, prompt=prompt)
    return ResolvedSkill(
        definition=defn,
        source_path=source or Path(f"/fake/{name}/SKILL.md"),
    )


# ===========================================================================
# Schema tests
# ===========================================================================


class TestSkillFrontmatter:
    def test_minimal(self):
        fm = SkillFrontmatter(name="ab", description="test")
        assert fm.name == "ab"
        assert fm.description == "test"
        assert fm.tools == []
        assert fm.requires.env == []
        assert fm.requires.bins == []
        assert fm.license == ""
        assert fm.metadata == {}

    def test_full(self):
        fm = SkillFrontmatter(
            name="web-researcher",
            description="Web research",
            license="MIT",
            compatibility="initrunner",
            metadata={"author": "test", "version": "1.0"},
            tools=[{"type": "web_reader"}],  # type: ignore[invalid-argument-type]
            requires=RequiresConfig(env=["API_KEY"], bins=["curl"]),
        )
        assert fm.name == "web-researcher"
        assert len(fm.tools) == 1
        assert isinstance(fm.tools[0], WebReaderToolConfig)
        assert fm.requires.env == ["API_KEY"]
        assert fm.requires.bins == ["curl"]

    def test_tools_parsed_via_parse_tool_list(self):
        fm = SkillFrontmatter(
            name="ab",
            description="test",
            tools=[  # type: ignore[invalid-argument-type]
                {"type": "filesystem", "root_path": "/tmp"},
                {"type": "http", "base_url": "https://x.com"},
            ],
        )
        assert isinstance(fm.tools[0], FileSystemToolConfig)
        assert isinstance(fm.tools[1], HttpToolConfig)

    def test_requires_config_defaults(self):
        rc = RequiresConfig()
        assert rc.env == []
        assert rc.bins == []

    def test_invalid_name_uppercase(self):
        with pytest.raises(ValidationError):
            SkillFrontmatter(name="MySkill", description="test")

    def test_invalid_name_starts_with_dash(self):
        with pytest.raises(ValidationError):
            SkillFrontmatter(name="-skill", description="test")

    def test_extra_fields_ignored(self):
        fm = SkillFrontmatter(
            name="ab",
            description="test",
            unknown_field="should be ignored",  # type: ignore[call-arg]
            another="also ignored",  # type: ignore[call-arg]
        )
        assert fm.name == "ab"
        assert not hasattr(fm, "unknown_field")


class TestSkillDefinition:
    def test_holds_frontmatter_and_prompt(self):
        fm = SkillFrontmatter(name="ab", description="test")
        sd = SkillDefinition(frontmatter=fm, prompt="Some instructions")
        assert sd.frontmatter.name == "ab"
        assert sd.prompt == "Some instructions"


class TestAgentSpecSkills:
    def test_skills_field_default_empty(self):
        spec = AgentSpec(
            role="test",
            model=ModelConfig(provider="openai", name="gpt-4o-mini"),
        )
        assert spec.skills == []

    def test_skills_field_accepts_strings(self):
        spec = AgentSpec(
            role="test",
            model=ModelConfig(provider="openai", name="gpt-4o-mini"),
            skills=["web-researcher", "./skills/code-tools.md"],
        )
        assert len(spec.skills) == 2
        assert spec.skills[0] == "web-researcher"


class TestParseToolList:
    def test_standalone_function(self):
        result = parse_tool_list([{"type": "datetime"}])
        assert len(result) == 1
        assert isinstance(result[0], DateTimeToolConfig)

    def test_non_list_passthrough(self):
        assert parse_tool_list("not a list") == "not a list"

    def test_empty_list(self):
        assert parse_tool_list([]) == []


# ===========================================================================
# Frontmatter parsing tests
# ===========================================================================


class TestParseFrontmatter:
    def test_valid(self):
        data, body = _parse_frontmatter(MINIMAL_SKILL_MD)
        assert data["name"] == "test-skill"
        assert data["description"] == "A test skill"
        assert "Test prompt body." in body

    def test_missing_opening_delimiter(self):
        with pytest.raises(SkillLoadError, match="must start with"):
            _parse_frontmatter("no frontmatter here")

    def test_missing_closing_delimiter(self):
        with pytest.raises(SkillLoadError, match="closing"):
            _parse_frontmatter("---\nname: test\n")

    def test_empty_frontmatter(self):
        content = "---\n---\nBody text"
        with pytest.raises(SkillLoadError, match="must be a YAML mapping"):
            _parse_frontmatter(content)

    def test_frontmatter_without_body(self):
        content = "---\nname: ab\ndescription: test\n---\n"
        data, body = _parse_frontmatter(content)
        assert data["name"] == "ab"
        assert body == ""

    def test_full_skill(self):
        data, body = _parse_frontmatter(FULL_SKILL_MD)
        assert data["name"] == "web-researcher"
        assert len(data["tools"]) == 2
        assert "Guidelines" in body


# ===========================================================================
# Loading tests
# ===========================================================================


class TestLoadSkill:
    def test_valid_file(self, tmp_path: Path):
        path = _write_skill(tmp_path, "test-skill", MINIMAL_SKILL_MD)
        sd = load_skill(path)
        assert sd.frontmatter.name == "test-skill"
        assert "Test prompt body." in sd.prompt

    def test_directory_with_skill_md(self, tmp_path: Path):
        _write_skill(tmp_path, "my-skill", FULL_SKILL_MD)
        sd = load_skill(tmp_path / "my-skill" / "SKILL.md")
        assert sd.frontmatter.name == "web-researcher"
        assert len(sd.frontmatter.tools) == 2

    def test_missing_file(self, tmp_path: Path):
        with pytest.raises(SkillLoadError, match="Cannot read"):
            load_skill(tmp_path / "nonexistent" / "SKILL.md")

    def test_invalid_frontmatter(self, tmp_path: Path):
        bad = "---\nname: 123\n---\nBody"
        path = _write_skill(tmp_path, "bad-skill", bad)
        with pytest.raises(SkillLoadError, match="Validation failed"):
            load_skill(path)

    def test_empty_tools_warning(self, tmp_path: Path, caplog):
        path = _write_skill(tmp_path, "community-skill", MINIMAL_SKILL_MD)
        ir_logger = logging.getLogger("initrunner")
        ir_logger.addHandler(caplog.handler)
        try:
            with caplog.at_level(logging.WARNING):
                sd = load_skill(path)
            assert sd.frontmatter.tools == []
            assert "no tool configs" in caplog.text
        finally:
            ir_logger.removeHandler(caplog.handler)


# ===========================================================================
# Resolution tests
# ===========================================================================


class TestResolveSkillPath:
    def test_explicit_md_path(self, tmp_path: Path):
        path = _write_flat_skill(tmp_path, "my-tool", MINIMAL_SKILL_MD)
        result = _resolve_skill_path("my-tool.md", role_dir=tmp_path, extra_dirs=None)
        assert result == path.resolve()

    def test_explicit_directory(self, tmp_path: Path):
        _write_skill(tmp_path, "my-skill", MINIMAL_SKILL_MD)
        result = _resolve_skill_path("./my-skill", role_dir=tmp_path, extra_dirs=None)
        assert result == (tmp_path / "my-skill" / "SKILL.md").resolve()

    def test_bare_name_from_role_dir_skills_directory(self, tmp_path: Path):
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        _write_skill(skills_dir, "web-tools", MINIMAL_SKILL_MD)
        result = _resolve_skill_path("web-tools", role_dir=tmp_path, extra_dirs=None)
        assert result == (skills_dir / "web-tools" / "SKILL.md").resolve()

    def test_bare_name_from_role_dir_skills_flat(self, tmp_path: Path):
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        _write_flat_skill(skills_dir, "web-tools", MINIMAL_SKILL_MD)
        result = _resolve_skill_path("web-tools", role_dir=tmp_path, extra_dirs=None)
        assert result == (skills_dir / "web-tools.md").resolve()

    def test_bare_name_from_global(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        from initrunner.config import get_home_dir

        global_dir = tmp_path / "skills"
        global_dir.mkdir(parents=True)
        _write_skill(global_dir, "global-skill", MINIMAL_SKILL_MD)

        monkeypatch.setenv("INITRUNNER_HOME", str(tmp_path))
        get_home_dir.cache_clear()
        try:
            result = _resolve_skill_path("global-skill", role_dir=None, extra_dirs=None)
        finally:
            get_home_dir.cache_clear()
        assert result == (global_dir / "global-skill" / "SKILL.md").resolve()

    def test_extra_dirs_precedence_over_global(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        from initrunner.config import get_home_dir

        global_dir = tmp_path / "skills"
        global_dir.mkdir(parents=True)
        _write_skill(global_dir, "shared-skill", MINIMAL_SKILL_MD)

        extra_dir = tmp_path / "extra"
        extra_dir.mkdir()
        extra_content = MINIMAL_SKILL_MD.replace("A test skill", "Extra version")
        _write_skill(extra_dir, "shared-skill", extra_content)

        monkeypatch.setenv("INITRUNNER_HOME", str(tmp_path))
        get_home_dir.cache_clear()
        try:
            result = _resolve_skill_path("shared-skill", role_dir=None, extra_dirs=[extra_dir])
        finally:
            get_home_dir.cache_clear()
        assert result == (extra_dir / "shared-skill" / "SKILL.md").resolve()

    def test_not_found_error(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        from initrunner.config import get_home_dir

        monkeypatch.setenv("INITRUNNER_HOME", str(tmp_path))
        get_home_dir.cache_clear()
        try:
            with pytest.raises(SkillLoadError, match="not found"):
                _resolve_skill_path("nonexistent", role_dir=tmp_path, extra_dirs=None)
        finally:
            get_home_dir.cache_clear()

    def test_deduplication_by_resolved_path(self, tmp_path: Path):
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        _write_skill(skills_dir, "my-skill", MINIMAL_SKILL_MD)

        results = resolve_skills(
            ["my-skill", "my-skill"],
            role_dir=tmp_path,
            extra_dirs=None,
        )
        assert len(results) == 1

    def test_order_preserved(self, tmp_path: Path):
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()

        skill_a = MINIMAL_SKILL_MD.replace("test-skill", "skill-aa")
        skill_b = MINIMAL_SKILL_MD.replace("test-skill", "skill-bb")
        _write_skill(skills_dir, "skill-aa", skill_a)
        _write_skill(skills_dir, "skill-bb", skill_b)

        results = resolve_skills(
            ["skill-aa", "skill-bb"],
            role_dir=tmp_path,
            extra_dirs=None,
        )
        assert len(results) == 2
        assert results[0].definition.frontmatter.name == "skill-aa"
        assert results[1].definition.frontmatter.name == "skill-bb"


# ===========================================================================
# Requirements tests
# ===========================================================================


class TestCheckRequirements:
    def test_met_env(self, tmp_path: Path):
        fm = SkillFrontmatter(name="ab", description="t", requires=RequiresConfig(env=["PATH"]))
        sd = SkillDefinition(frontmatter=fm, prompt="")
        statuses = check_requirements(sd)
        assert len(statuses) == 1
        assert statuses[0].met is True
        assert statuses[0].kind == "env"

    def test_unmet_env(self, tmp_path: Path):
        fm = SkillFrontmatter(
            name="ab", description="t", requires=RequiresConfig(env=["NONEXISTENT_VAR_12345"])
        )
        sd = SkillDefinition(frontmatter=fm, prompt="")
        statuses = check_requirements(sd)
        assert statuses[0].met is False
        assert "not set" in statuses[0].detail

    def test_met_bin(self):
        fm = SkillFrontmatter(name="ab", description="t", requires=RequiresConfig(bins=["python3"]))
        sd = SkillDefinition(frontmatter=fm, prompt="")
        statuses = check_requirements(sd)
        assert len(statuses) == 1
        assert statuses[0].met is True
        assert statuses[0].kind == "bin"

    def test_unmet_bin(self):
        fm = SkillFrontmatter(
            name="ab", description="t", requires=RequiresConfig(bins=["nonexistent_binary_xyz"])
        )
        sd = SkillDefinition(frontmatter=fm, prompt="")
        statuses = check_requirements(sd)
        assert statuses[0].met is False
        assert "not found on PATH" in statuses[0].detail

    def test_empty_requires(self):
        fm = SkillFrontmatter(name="ab", description="t")
        sd = SkillDefinition(frontmatter=fm, prompt="")
        statuses = check_requirements(sd)
        assert statuses == []


# ===========================================================================
# Merging tests
# ===========================================================================


class TestMergeSkillTools:
    def test_skill_tools_first_role_tools_second(self):
        skill = _make_resolved_skill("sk", tools=[{"type": "web_reader"}])
        role_tools = [DateTimeToolConfig()]

        merged = merge_skill_tools([skill], role_tools)
        types = [t.type for t in merged]
        assert types == ["web_reader", "datetime"]

    def test_multiple_skills_in_order(self):
        skill_a = _make_resolved_skill("aa", tools=[{"type": "web_reader"}])
        skill_b = _make_resolved_skill("bb", tools=[{"type": "filesystem"}])

        merged = merge_skill_tools([skill_a, skill_b], [])
        types = [t.type for t in merged]
        assert types == ["web_reader", "filesystem"]

    def test_empty_skill_tools(self):
        skill = _make_resolved_skill("sk", tools=[])
        role_tools = [DateTimeToolConfig()]

        merged = merge_skill_tools([skill], role_tools)
        assert len(merged) == 1
        assert merged[0].type == "datetime"

    def test_role_overrides_skill_same_type(self, caplog):
        skill = _make_resolved_skill("sk", tools=[{"type": "web_reader", "timeout_seconds": 10}])
        role_tools = [WebReaderToolConfig(timeout_seconds=30)]

        ir_logger = logging.getLogger("initrunner")
        ir_logger.addHandler(caplog.handler)
        try:
            with caplog.at_level(logging.WARNING):
                merged = merge_skill_tools([skill], role_tools)

            assert len(merged) == 1
            assert isinstance(merged[0], WebReaderToolConfig)
            assert merged[0].timeout_seconds == 30
            assert "overrides same type" in caplog.text
        finally:
            ir_logger.removeHandler(caplog.handler)

    def test_later_skill_overrides_earlier(self, caplog):
        skill_a = _make_resolved_skill("aa", tools=[{"type": "web_reader", "timeout_seconds": 5}])
        skill_b = _make_resolved_skill("bb", tools=[{"type": "web_reader", "timeout_seconds": 20}])

        ir_logger = logging.getLogger("initrunner")
        ir_logger.addHandler(caplog.handler)
        try:
            with caplog.at_level(logging.WARNING):
                merged = merge_skill_tools([skill_a, skill_b], [])

            assert len(merged) == 1
            assert isinstance(merged[0], WebReaderToolConfig)
            assert merged[0].timeout_seconds == 20
            assert "overrides same type from skill 'aa'" in caplog.text
        finally:
            ir_logger.removeHandler(caplog.handler)


# ===========================================================================
# Prompt building tests
# ===========================================================================


class TestBuildSkillSystemPrompt:
    def test_structured_header(self):
        skill = _make_resolved_skill("web-tools", prompt="Use web tools wisely.")
        result = build_skill_system_prompt([skill])
        assert "## Skills" in result
        assert "### Skill: web-tools" in result
        assert "Use web tools wisely." in result
        assert "additional capabilities" in result

    def test_multiple_skills(self):
        skill_a = _make_resolved_skill("aa", prompt="Skill A instructions.")
        skill_b = _make_resolved_skill("bb", prompt="Skill B instructions.")
        result = build_skill_system_prompt([skill_a, skill_b])
        assert "### Skill: aa" in result
        assert "### Skill: bb" in result
        assert result.index("### Skill: aa") < result.index("### Skill: bb")

    def test_empty_prompt_skipped(self):
        skill = _make_resolved_skill("sk", prompt="")
        result = build_skill_system_prompt([skill])
        assert result == ""

    def test_no_skills_empty_string(self):
        result = build_skill_system_prompt([])
        assert result == ""


# ===========================================================================
# CLI tests
# ===========================================================================


class TestSkillCLI:
    def test_skill_validate_valid(self, tmp_path: Path):
        from typer.testing import CliRunner

        from initrunner.cli.main import app

        _write_skill(tmp_path, "test-skill", FULL_SKILL_MD)
        runner = CliRunner()
        result = runner.invoke(app, ["skill", "validate", str(tmp_path / "test-skill")])
        assert result.exit_code == 0
        assert "Valid" in result.output

    def test_skill_validate_invalid(self, tmp_path: Path):
        from typer.testing import CliRunner

        from initrunner.cli.main import app

        bad_skill = "---\nname: 123\n---\nbody"
        path = _write_skill(tmp_path, "bad-skill", bad_skill)
        runner = CliRunner()
        result = runner.invoke(app, ["skill", "validate", str(path)])
        assert result.exit_code == 1
        assert "Invalid" in result.output

    def test_skill_list_empty(self, tmp_path: Path, monkeypatch):
        from typer.testing import CliRunner

        from initrunner.cli.main import app

        monkeypatch.chdir(tmp_path)
        runner = CliRunner()
        result = runner.invoke(app, ["skill", "list"])
        assert result.exit_code == 0
        assert "No skills found" in result.output

    def test_skill_list_finds_skills(self, tmp_path: Path, monkeypatch):
        from typer.testing import CliRunner

        from initrunner.cli.main import app

        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        _write_skill(skills_dir, "my-skill", FULL_SKILL_MD)

        monkeypatch.chdir(tmp_path)
        runner = CliRunner()
        result = runner.invoke(app, ["skill", "list"])
        assert result.exit_code == 0
        assert "web-researcher" in result.output

    def test_init_template_skill(self, tmp_path: Path, monkeypatch):
        from typer.testing import CliRunner

        from initrunner.cli.main import app

        monkeypatch.chdir(tmp_path)
        runner = CliRunner()
        result = runner.invoke(app, ["init", "--template", "skill", "--name", "web-tools"])
        assert result.exit_code == 0
        assert "Created" in result.output
        assert (tmp_path / "web-tools" / "SKILL.md").exists()
