"""Tests for auto-discovered skills (agentskills.io progressive disclosure)."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from initrunner.agent.auto_skills import (
    DiscoveredSkill,
    _list_resources,
    build_activate_skill_toolset,
    build_catalog_prompt,
    discover_skills,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

MINIMAL_SKILL = textwrap.dedent("""\
    ---
    name: test-skill
    description: A test skill for auto-discovery
    ---

    Test prompt body.
""")

SKILL_NO_DESC = textwrap.dedent("""\
    ---
    name: no-desc-skill
    ---

    Missing description.
""")

SKILL_BAD_YAML = "---\n: invalid yaml {{{\n---\nbody"

SKILL_LENIENT = textwrap.dedent("""\
    ---
    name: lenient skill with spaces
    description: This has an invalid name pattern but still has name+desc
    ---

    Body here.
""")


def _make_skill_dir(base: Path, name: str, content: str) -> Path:
    """Create a {base}/{name}/SKILL.md file."""
    d = base / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(content)
    return d


# ---------------------------------------------------------------------------
# discover_skills
# ---------------------------------------------------------------------------


class TestDiscoverSkills:
    def test_discovers_role_local_skills(self, tmp_path: Path) -> None:
        role_dir = tmp_path / "project"
        role_dir.mkdir()
        _make_skill_dir(role_dir / "skills", "my-skill", MINIMAL_SKILL)

        result = discover_skills(role_dir=role_dir, extra_dirs=None)
        assert len(result) == 1
        assert result[0].name == "test-skill"
        assert result[0].scope == "role-local"

    def test_discovers_project_level_skills(self, tmp_path: Path) -> None:
        role_dir = tmp_path / "project"
        role_dir.mkdir()
        _make_skill_dir(role_dir / ".agents" / "skills", "my-skill", MINIMAL_SKILL)

        result = discover_skills(role_dir=role_dir, extra_dirs=None)
        assert len(result) == 1
        assert result[0].scope == "project"

    def test_discovers_extra_dir_skills(self, tmp_path: Path) -> None:
        extra = tmp_path / "extra-skills"
        _make_skill_dir(extra, "ext-skill", MINIMAL_SKILL)

        result = discover_skills(role_dir=None, extra_dirs=[extra])
        assert len(result) == 1
        assert result[0].scope == "extra"

    def test_discovers_user_level_skills(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        user_skills = tmp_path / "home" / ".agents" / "skills"
        _make_skill_dir(user_skills, "user-skill", MINIMAL_SKILL)
        monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
        # Also ensure get_skills_dir doesn't find anything extra
        monkeypatch.setenv("INITRUNNER_HOME", str(tmp_path / "ir-home"))

        result = discover_skills(role_dir=None, extra_dirs=None)
        assert len(result) == 1
        assert result[0].scope == "user"

    def test_priority_dedup_first_scope_wins(self, tmp_path: Path) -> None:
        """Role-local should shadow project-level for same skill name."""
        role_dir = tmp_path / "project"
        role_dir.mkdir()

        local_skill = textwrap.dedent("""\
            ---
            name: test-skill
            description: Role-local version
            ---
            Local body.
        """)
        project_skill = textwrap.dedent("""\
            ---
            name: test-skill
            description: Project version
            ---
            Project body.
        """)
        _make_skill_dir(role_dir / "skills", "my-skill", local_skill)
        _make_skill_dir(role_dir / ".agents" / "skills", "my-skill", project_skill)

        result = discover_skills(role_dir=role_dir, extra_dirs=None)
        assert len(result) == 1
        assert result[0].description == "Role-local version"
        assert result[0].scope == "role-local"

    def test_excludes_explicit_paths(self, tmp_path: Path) -> None:
        role_dir = tmp_path / "project"
        role_dir.mkdir()
        skill_dir = _make_skill_dir(role_dir / "skills", "my-skill", MINIMAL_SKILL)
        skill_path = (skill_dir / "SKILL.md").resolve()

        result = discover_skills(role_dir=role_dir, extra_dirs=None, exclude_paths={skill_path})
        assert len(result) == 0

    def test_max_skills_cap(self, tmp_path: Path) -> None:
        role_dir = tmp_path / "project"
        role_dir.mkdir()
        for i in range(5):
            content = textwrap.dedent(f"""\
                ---
                name: skill-{i:02d}
                description: Skill number {i}
                ---
                Body {i}.
            """)
            _make_skill_dir(role_dir / "skills", f"skill-{i:02d}", content)

        result = discover_skills(role_dir=role_dir, extra_dirs=None, max_skills=3)
        assert len(result) == 3

    def test_skips_no_description(self, tmp_path: Path) -> None:
        role_dir = tmp_path / "project"
        role_dir.mkdir()
        _make_skill_dir(role_dir / "skills", "bad-skill", SKILL_NO_DESC)

        result = discover_skills(role_dir=role_dir, extra_dirs=None)
        assert len(result) == 0

    def test_skips_bad_yaml(self, tmp_path: Path) -> None:
        role_dir = tmp_path / "project"
        role_dir.mkdir()
        _make_skill_dir(role_dir / "skills", "bad-skill", SKILL_BAD_YAML)

        result = discover_skills(role_dir=role_dir, extra_dirs=None)
        assert len(result) == 0

    def test_skips_skip_dirs(self, tmp_path: Path) -> None:
        role_dir = tmp_path / "project"
        role_dir.mkdir()
        _make_skill_dir(role_dir / "skills", "node_modules", MINIMAL_SKILL)
        _make_skill_dir(role_dir / "skills", "__pycache__", MINIMAL_SKILL)

        result = discover_skills(role_dir=role_dir, extra_dirs=None)
        assert len(result) == 0

    def test_skips_flat_md_files(self, tmp_path: Path) -> None:
        """Auto-discovery only picks up directory format, not flat .md."""
        role_dir = tmp_path / "project"
        skills = role_dir / "skills"
        skills.mkdir(parents=True)
        (skills / "flat-skill.md").write_text(MINIMAL_SKILL)

        result = discover_skills(role_dir=role_dir, extra_dirs=None)
        assert len(result) == 0

    def test_lenient_frontmatter(self, tmp_path: Path) -> None:
        """Skills with invalid name patterns still load via lenient fallback."""
        role_dir = tmp_path / "project"
        role_dir.mkdir()
        _make_skill_dir(role_dir / "skills", "lenient-skill", SKILL_LENIENT)

        result = discover_skills(role_dir=role_dir, extra_dirs=None)
        assert len(result) == 1
        assert result[0].name == "lenient skill with spaces"

    def test_env_skill_dir(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        env_dir = tmp_path / "env-skills"
        _make_skill_dir(env_dir, "env-skill", MINIMAL_SKILL)
        monkeypatch.setenv("INITRUNNER_SKILL_DIR", str(env_dir))

        result = discover_skills(role_dir=None, extra_dirs=None)
        # Should find it via INITRUNNER_SKILL_DIR
        found_names = [s.name for s in result]
        assert "test-skill" in found_names

    def test_no_role_dir(self) -> None:
        """No role_dir should not crash."""
        result = discover_skills(role_dir=None, extra_dirs=None)
        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# build_catalog_prompt
# ---------------------------------------------------------------------------


class TestBuildCatalogPrompt:
    def test_catalog_format(self) -> None:
        skills = [
            DiscoveredSkill(
                name="pdf-processing",
                description="Extract PDF text, fill forms.",
                path=Path("/fake/skills/pdf/SKILL.md"),
                scope="user",
            ),
            DiscoveredSkill(
                name="code-review",
                description="Code review guidelines.",
                path=Path("/fake/skills/review/SKILL.md"),
                scope="project",
            ),
        ]
        prompt = build_catalog_prompt(skills)
        assert "## Available Skills" in prompt
        assert "<available_skills>" in prompt
        assert "</available_skills>" in prompt
        assert '<skill name="pdf-processing">Extract PDF text, fill forms.</skill>' in prompt
        assert '<skill name="code-review">Code review guidelines.</skill>' in prompt

    def test_empty_skills(self) -> None:
        prompt = build_catalog_prompt([])
        assert "<available_skills>" in prompt
        assert "</available_skills>" in prompt


# ---------------------------------------------------------------------------
# activate_skill tool
# ---------------------------------------------------------------------------


class TestActivateSkill:
    def test_activate_returns_content(self, tmp_path: Path) -> None:
        skill_dir = _make_skill_dir(tmp_path, "my-skill", MINIMAL_SKILL)
        skills = [
            DiscoveredSkill(
                name="test-skill",
                description="A test skill",
                path=(skill_dir / "SKILL.md").resolve(),
                scope="role-local",
            )
        ]
        activated: set[str] = set()
        toolset = build_activate_skill_toolset(skills, activated)

        # Extract the tool function
        tool_fn = _get_tool_fn(toolset, "activate_skill")
        result = tool_fn("test-skill")

        assert '<skill_content name="test-skill">' in result
        assert "Test prompt body." in result
        assert "</skill_content>" in result
        assert "test-skill" in activated

    def test_activate_dedup(self, tmp_path: Path) -> None:
        skill_dir = _make_skill_dir(tmp_path, "my-skill", MINIMAL_SKILL)
        skills = [
            DiscoveredSkill(
                name="test-skill",
                description="A test skill",
                path=(skill_dir / "SKILL.md").resolve(),
                scope="role-local",
            )
        ]
        activated: set[str] = set()
        toolset = build_activate_skill_toolset(skills, activated)
        tool_fn = _get_tool_fn(toolset, "activate_skill")

        tool_fn("test-skill")
        result = tool_fn("test-skill")
        assert "already active" in result

    def test_activate_unknown(self, tmp_path: Path) -> None:
        toolset = build_activate_skill_toolset([], set())
        tool_fn = _get_tool_fn(toolset, "activate_skill")
        result = tool_fn("nonexistent")
        assert "Unknown skill" in result

    def test_activate_lists_resources(self, tmp_path: Path) -> None:
        skill_dir = _make_skill_dir(tmp_path, "res-skill", MINIMAL_SKILL)
        (skill_dir / "example.py").write_text("print('hello')")
        (skill_dir / "data.json").write_text("{}")

        skills = [
            DiscoveredSkill(
                name="test-skill",
                description="A test skill",
                path=(skill_dir / "SKILL.md").resolve(),
                scope="role-local",
            )
        ]
        activated: set[str] = set()
        toolset = build_activate_skill_toolset(skills, activated)
        tool_fn = _get_tool_fn(toolset, "activate_skill")
        result = tool_fn("test-skill")

        assert "<skill_resources>" in result
        assert "<file>data.json</file>" in result
        assert "<file>example.py</file>" in result


# ---------------------------------------------------------------------------
# _list_resources
# ---------------------------------------------------------------------------


class TestListResources:
    def test_excludes_skill_md(self, tmp_path: Path) -> None:
        (tmp_path / "SKILL.md").write_text("content")
        (tmp_path / "helper.py").write_text("pass")
        resources = _list_resources(tmp_path)
        assert "helper.py" in resources
        assert "SKILL.md" not in resources

    def test_caps_at_max(self, tmp_path: Path) -> None:
        for i in range(35):
            (tmp_path / f"file{i:03d}.txt").write_text("x")
        resources = _list_resources(tmp_path)
        assert len(resources) == 30

    def test_skips_venv(self, tmp_path: Path) -> None:
        venv = tmp_path / ".venv"
        venv.mkdir()
        (venv / "bin.py").write_text("x")
        (tmp_path / "good.py").write_text("x")
        resources = _list_resources(tmp_path)
        assert "good.py" in resources
        assert any(".venv" in r for r in resources) is False


# ---------------------------------------------------------------------------
# Compaction exemption
# ---------------------------------------------------------------------------


class TestCompactionExemption:
    def test_activate_skill_not_truncated(self) -> None:
        from pydantic_ai.messages import ModelRequest, ToolReturnPart

        from initrunner.agent.history_compaction import _serialize_messages_for_summary

        long_content = "x" * 500
        messages = [
            ModelRequest(
                parts=[
                    ToolReturnPart(
                        tool_name="activate_skill",
                        content=long_content,
                    )
                ]
            ),
        ]
        text = _serialize_messages_for_summary(messages)
        assert "[skill instructions preserved in context]" in text
        assert "[truncated]" not in text

    def test_other_tool_still_truncated(self) -> None:
        from pydantic_ai.messages import ModelRequest, ToolReturnPart

        from initrunner.agent.history_compaction import _serialize_messages_for_summary

        long_content = "x" * 500
        messages = [
            ModelRequest(
                parts=[
                    ToolReturnPart(
                        tool_name="some_other_tool",
                        content=long_content,
                    )
                ]
            ),
        ]
        text = _serialize_messages_for_summary(messages)
        assert "[truncated]" in text


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


class TestAutoSkillsConfig:
    def test_default_enabled(self) -> None:
        from initrunner.agent.schema.role import AutoSkillsConfig

        config = AutoSkillsConfig()
        assert config.enabled is True
        assert config.max_skills == 50

    def test_disabled(self) -> None:
        from initrunner.agent.schema.role import AutoSkillsConfig

        config = AutoSkillsConfig(enabled=False)
        assert config.enabled is False

    def test_in_agent_spec(self) -> None:
        from initrunner.agent.schema.base import ModelConfig
        from initrunner.agent.schema.role import AgentSpec, AutoSkillsConfig

        spec = AgentSpec(
            role="test",
            model=ModelConfig(provider="openai", name="gpt-5-mini"),
            auto_skills=AutoSkillsConfig(enabled=False, max_skills=10),
        )
        assert spec.auto_skills.enabled is False
        assert spec.auto_skills.max_skills == 10

    def test_default_in_agent_spec(self) -> None:
        from initrunner.agent.schema.base import ModelConfig
        from initrunner.agent.schema.role import AgentSpec

        spec = AgentSpec(
            role="test",
            model=ModelConfig(provider="openai", name="gpt-5-mini"),
        )
        assert spec.auto_skills.enabled is True


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_tool_fn(toolset, name: str):
    """Extract a tool's raw function from a FunctionToolset for direct testing."""
    return toolset.tools[name].function
