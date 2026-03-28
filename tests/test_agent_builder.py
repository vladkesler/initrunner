"""Tests for the agent builder service layer."""

from __future__ import annotations

import textwrap
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from initrunner.services.agent_builder import (
    BuilderSession,
    TurnResult,
    ValidationIssue,
    _strip_yaml_fences,
    _validate_yaml,
    build_next_steps,
    build_tool_summary,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_VALID_YAML = textwrap.dedent("""\
    apiVersion: initrunner/v1
    kind: Agent
    metadata:
      name: test-agent
      description: A test agent
    spec:
      role: You are a helpful assistant.
      model:
        provider: openai
        name: gpt-5-mini
      guardrails:
        timeout_seconds: 30
""")

_VALID_YAML_WITH_INGEST = textwrap.dedent("""\
    apiVersion: initrunner/v1
    kind: Agent
    metadata:
      name: rag-agent
      description: RAG agent
    spec:
      role: You are a knowledge assistant.
      model:
        provider: openai
        name: gpt-5-mini
      guardrails:
        timeout_seconds: 30
      ingest:
        sources:
          - "./docs/**/*.md"
        chunking:
          strategy: fixed
          chunk_size: 512
          chunk_overlap: 50
""")

_VALID_YAML_WITH_TRIGGERS = textwrap.dedent("""\
    apiVersion: initrunner/v1
    kind: Agent
    metadata:
      name: daemon-agent
      description: Daemon agent
    spec:
      role: You monitor events.
      model:
        provider: openai
        name: gpt-5-mini
      guardrails:
        timeout_seconds: 30
      triggers:
        - type: cron
          schedule: "0 9 * * 1"
          prompt: "Weekly report"
""")

_VALID_YAML_WITH_MEMORY = textwrap.dedent("""\
    apiVersion: initrunner/v1
    kind: Agent
    metadata:
      name: memory-agent
      description: Memory agent
    spec:
      role: You have long-term memory.
      model:
        provider: openai
        name: gpt-5-mini
      guardrails:
        timeout_seconds: 30
      memory:
        max_sessions: 10
        semantic:
          max_memories: 1000
""")

_VALID_YAML_WITH_DISCORD = textwrap.dedent("""\
    apiVersion: initrunner/v1
    kind: Agent
    metadata:
      name: discord-bot
      description: Discord bot
    spec:
      role: You respond to Discord messages.
      model:
        provider: openai
        name: gpt-5-mini
      guardrails:
        timeout_seconds: 30
      triggers:
        - type: discord
          token_env: DISCORD_BOT_TOKEN
          channel_ids: []
          prompt_template: "{message}"
""")

_VALID_YAML_WITH_TELEGRAM = textwrap.dedent("""\
    apiVersion: initrunner/v1
    kind: Agent
    metadata:
      name: telegram-bot
      description: Telegram bot
    spec:
      role: You respond to Telegram messages.
      model:
        provider: openai
        name: gpt-5-mini
      guardrails:
        timeout_seconds: 30
      triggers:
        - type: telegram
          token_env: TELEGRAM_BOT_TOKEN
          allowed_users: []
          prompt_template: "{message}"
""")


@dataclass
class _FakeResult:
    """Mimics pydantic_ai RunResult for testing."""

    output: str
    _messages: list

    def all_messages(self):
        return self._messages


def _make_fake_agent(response_text: str):
    """Create a mock PydanticAI Agent that returns a canned response."""
    agent = MagicMock()
    agent.run_sync.return_value = _FakeResult(
        output=response_text,
        _messages=[{"role": "assistant", "content": response_text}],
    )
    return agent


# ---------------------------------------------------------------------------
# ValidationIssue / TurnResult
# ---------------------------------------------------------------------------


class TestTurnResult:
    def test_ready_when_no_errors(self):
        tr = TurnResult(
            explanation="ok",
            yaml_text=_VALID_YAML,
            issues=[ValidationIssue(field="x", message="minor", severity="warning")],
        )
        assert tr.ready is True

    def test_not_ready_when_errors(self):
        tr = TurnResult(
            explanation="bad",
            yaml_text="invalid",
            issues=[ValidationIssue(field="x", message="broken", severity="error")],
        )
        assert tr.ready is False

    def test_ready_when_no_issues(self):
        tr = TurnResult(explanation="ok", yaml_text=_VALID_YAML, issues=[])
        assert tr.ready is True


# ---------------------------------------------------------------------------
# _validate_yaml
# ---------------------------------------------------------------------------


class TestValidateYaml:
    def test_valid_yaml(self):
        role, issues = _validate_yaml(_VALID_YAML)
        assert role is not None
        assert role.metadata.name == "test-agent"
        errors = [i for i in issues if i.severity == "error"]
        assert len(errors) == 0

    def test_invalid_yaml_syntax(self):
        role, issues = _validate_yaml("{{{{bad yaml")
        assert role is None
        assert any(i.severity == "error" for i in issues)
        assert any("syntax" in i.message.lower() for i in issues)

    def test_yaml_not_a_mapping(self):
        role, issues = _validate_yaml("- item1\n- item2")
        assert role is None
        assert any("mapping" in i.message.lower() for i in issues)

    def test_schema_validation_error(self):
        role, issues = _validate_yaml("apiVersion: bad\nkind: Agent\n")
        assert role is None
        assert any(i.severity == "error" for i in issues)

    def test_short_system_prompt_warning(self):
        short_yaml = _VALID_YAML.replace("You are a helpful assistant.", "Hi")
        _role, issues = _validate_yaml(short_yaml)
        warnings = [i for i in issues if i.severity == "warning"]
        assert any("short" in w.message.lower() for w in warnings)

    def test_capability_tool_conflict_error(self):
        conflict_yaml = textwrap.dedent("""\
            apiVersion: initrunner/v1
            kind: Agent
            metadata:
              name: conflict-test
              description: test
              spec_version: 2
            spec:
              role: You are helpful.
              model:
                provider: anthropic
                name: claude-sonnet-4-5-20250929
              tools:
                - type: search
              capabilities:
                - WebSearch
        """)
        _role, issues = _validate_yaml(conflict_yaml)
        errors = [i for i in issues if i.severity == "error"]
        assert any("WebSearch" in e.message and "search" in e.message for e in errors)


# ---------------------------------------------------------------------------
# _strip_yaml_fences
# ---------------------------------------------------------------------------


class TestStripYamlFences:
    def test_no_fences(self):
        assert _strip_yaml_fences(_VALID_YAML) == _VALID_YAML.strip()

    def test_yaml_fences(self):
        fenced = f"```yaml\n{_VALID_YAML}```"
        assert _strip_yaml_fences(fenced) == _VALID_YAML.strip()

    def test_plain_fences(self):
        fenced = f"```\n{_VALID_YAML}```"
        assert _strip_yaml_fences(fenced) == _VALID_YAML.strip()

    def test_with_surrounding_whitespace(self):
        fenced = f"  \n```yaml\n{_VALID_YAML}```\n  "
        result = _strip_yaml_fences(fenced)
        assert not result.startswith("```")
        assert not result.endswith("```")


# ---------------------------------------------------------------------------
# build_tool_summary
# ---------------------------------------------------------------------------


class TestBuildToolSummary:
    def test_returns_string(self):
        summary = build_tool_summary()
        assert isinstance(summary, str)
        assert "Tools" in summary

    def test_includes_filesystem(self):
        summary = build_tool_summary()
        assert "filesystem" in summary

    def test_includes_git(self):
        summary = build_tool_summary()
        assert "git" in summary


# ---------------------------------------------------------------------------
# build_next_steps
# ---------------------------------------------------------------------------


class TestBuildNextSteps:
    def test_default_run_hint(self):
        role, _ = _validate_yaml(_VALID_YAML)
        assert role is not None
        steps = build_next_steps(role, Path("role.yaml"))
        assert any("initrunner run" in s for s in steps)
        assert any("validate" in s for s in steps)

    def test_ingest_hint(self):
        role, _ = _validate_yaml(_VALID_YAML_WITH_INGEST)
        assert role is not None
        steps = build_next_steps(role, Path("role.yaml"))
        assert any("ingest" in s for s in steps)

    def test_daemon_hint(self):
        role, _ = _validate_yaml(_VALID_YAML_WITH_TRIGGERS)
        assert role is not None
        steps = build_next_steps(role, Path("role.yaml"))
        assert any("daemon" in s for s in steps)

    def test_memory_hint(self):
        role, _ = _validate_yaml(_VALID_YAML_WITH_MEMORY)
        assert role is not None
        steps = build_next_steps(role, Path("role.yaml"))
        assert any("-i" in s for s in steps)

    def test_discord_trigger_hints(self):
        role, _ = _validate_yaml(_VALID_YAML_WITH_DISCORD)
        assert role is not None
        steps = build_next_steps(role, Path("role.yaml"))
        assert any("DISCORD_BOT_TOKEN" in s for s in steps)
        assert any("--extra discord" in s for s in steps)
        assert any("--daemon" in s for s in steps)

    def test_telegram_trigger_hints(self):
        role, _ = _validate_yaml(_VALID_YAML_WITH_TELEGRAM)
        assert role is not None
        steps = build_next_steps(role, Path("role.yaml"))
        assert any("TELEGRAM_BOT_TOKEN" in s for s in steps)
        assert any("--extra telegram" in s for s in steps)
        assert any("--daemon" in s for s in steps)


# ---------------------------------------------------------------------------
# BuilderSession -- property caching
# ---------------------------------------------------------------------------


class TestBuilderSessionProperties:
    def test_yaml_text_setter_invalidates_cache(self):
        session = BuilderSession()
        session._yaml_text = _VALID_YAML
        # Force cache population
        _ = session.role
        assert session._role_cache is not None
        assert session._issues_cache is not None

        # Now set via property setter -- should reflect new YAML
        session.yaml_text = _VALID_YAML_WITH_MEMORY
        # Canonicalizer re-parses, so cache is populated with new role
        assert session._role_cache is not None
        assert session._role_cache.metadata.name == "memory-agent"

    def test_role_property_parses_on_demand(self):
        session = BuilderSession()
        session._yaml_text = _VALID_YAML
        role = session.role
        assert role is not None
        assert role.metadata.name == "test-agent"

    def test_issues_property_on_valid_yaml(self):
        session = BuilderSession()
        session._yaml_text = _VALID_YAML
        issues = session.issues
        errors = [i for i in issues if i.severity == "error"]
        assert len(errors) == 0

    def test_issues_property_on_empty_yaml(self):
        session = BuilderSession()
        assert session.issues == []

    def test_role_property_on_empty_yaml(self):
        session = BuilderSession()
        assert session.role is None


# ---------------------------------------------------------------------------
# BuilderSession -- seed flows (no LLM)
# ---------------------------------------------------------------------------


class TestBuilderSessionSeedBlank:
    def test_seed_blank(self):
        session = BuilderSession()
        turn = session.seed_blank("openai")
        assert turn.yaml_text
        assert "my-agent" in turn.yaml_text
        assert session.seed_source == "blank"
        raw = yaml.safe_load(turn.yaml_text)
        assert raw["spec"]["model"]["provider"] == "openai"

    def test_seed_blank_with_model(self):
        session = BuilderSession()
        turn = session.seed_blank("openai", "gpt-4o")
        assert "gpt-4o" in turn.yaml_text


class TestBuilderSessionSeedTemplate:
    def test_seed_template_basic(self):
        session = BuilderSession()
        turn = session.seed_template("basic", "openai")
        assert turn.yaml_text
        assert session.seed_source == "template:basic"

    def test_seed_template_rag(self):
        session = BuilderSession()
        turn = session.seed_template("rag", "openai")
        assert "ingest" in turn.yaml_text
        assert session.seed_source == "template:rag"

    def test_seed_template_daemon(self):
        session = BuilderSession()
        turn = session.seed_template("daemon", "openai")
        assert "triggers" in turn.yaml_text

    def test_seed_template_memory(self):
        session = BuilderSession()
        turn = session.seed_template("memory", "openai")
        assert "memory" in turn.yaml_text
        parsed = yaml.safe_load(turn.yaml_text)
        assert "memory" in parsed["spec"], "memory YAML key missing after canonicalization"

    def test_seed_template_unknown_raises(self):
        session = BuilderSession()
        with pytest.raises(ValueError, match="Unknown template"):
            session.seed_template("nonexistent", "openai")

    def test_seed_template_tool_raises(self):
        session = BuilderSession()
        with pytest.raises(ValueError, match="produces a tool scaffold"):
            session.seed_template("tool", "openai")

    def test_seed_template_skill_raises(self):
        session = BuilderSession()
        with pytest.raises(ValueError, match="produces a skill scaffold"):
            session.seed_template("skill", "openai")


class TestBuilderSessionSeedFile:
    def test_seed_from_file(self, tmp_path):
        f = tmp_path / "role.yaml"
        f.write_text(_VALID_YAML)
        session = BuilderSession()
        session.seed_from_file(f)
        assert session.role is not None
        assert session.role.metadata.name == "test-agent"
        assert "file:" in session.seed_source

    def test_seed_from_file_not_found(self, tmp_path):
        session = BuilderSession()
        with pytest.raises(FileNotFoundError):
            session.seed_from_file(tmp_path / "missing.yaml")


class TestBuilderSessionSeedExample:
    @patch("initrunner.examples.get_example")
    def test_seed_from_example_single_file(self, mock_get):
        mock_get.return_value = MagicMock(
            primary_content=_VALID_YAML,
            description="A test example",
            multi_file=False,
            files=["role.yaml"],
            primary_file="role.yaml",
        )
        session = BuilderSession()
        session.seed_from_example("hello-world")
        assert session.role is not None
        assert session.role.metadata.name == "test-agent"
        assert session.omitted_assets == []

    @patch("initrunner.examples.get_example")
    def test_seed_from_example_multi_file(self, mock_get):
        mock_get.return_value = MagicMock(
            primary_content=_VALID_YAML,
            description="Multi file example",
            multi_file=True,
            files=["role.yaml", "skills/review/SKILL.md", "config.json"],
            primary_file="role.yaml",
        )
        session = BuilderSession()
        turn = session.seed_from_example("multi-example")
        assert session.role is not None
        assert session.role.metadata.name == "test-agent"
        assert "skills/review/SKILL.md" in session.omitted_assets
        assert "config.json" in session.omitted_assets
        assert "role.yaml" not in session.omitted_assets
        assert "omitted" in turn.explanation.lower() or "additional" in turn.explanation.lower()

    @patch("initrunner.examples.get_example")
    def test_seed_from_example_not_found(self, mock_get):
        from initrunner.examples import ExampleNotFoundError

        mock_get.side_effect = ExampleNotFoundError("nope")
        session = BuilderSession()
        with pytest.raises(ValueError, match="not found"):
            session.seed_from_example("nonexistent")


# ---------------------------------------------------------------------------
# BuilderSession -- seed_description (mocked LLM)
# ---------------------------------------------------------------------------


class TestBuilderSessionSeedDescription:
    @patch("initrunner.services.agent_builder.BuilderSession._get_agent")
    def test_seed_description(self, mock_get_agent):
        response = f"Here is your agent:\n\n```yaml\n{_VALID_YAML}```"
        mock_get_agent.return_value = _make_fake_agent(response)

        session = BuilderSession()
        session.seed_description("a code review bot", "openai")
        assert session.role is not None
        assert session.role.metadata.name == "test-agent"
        assert session.seed_source == "description"

    @patch("initrunner.services.agent_builder.BuilderSession._get_agent")
    def test_seed_description_with_name_hint(self, mock_get_agent):
        response = f"```yaml\n{_VALID_YAML}```"
        agent = _make_fake_agent(response)
        mock_get_agent.return_value = agent

        session = BuilderSession()
        session.seed_description("a chatbot", "openai", name_hint="my-bot")
        call_args = agent.run_sync.call_args
        assert "my-bot" in call_args[0][0]


# ---------------------------------------------------------------------------
# BuilderSession -- refine (mocked LLM)
# ---------------------------------------------------------------------------


class TestBuilderSessionRefine:
    @patch("initrunner.services.agent_builder.BuilderSession._get_agent")
    def test_refine_updates_yaml(self, mock_get_agent):
        updated_yaml = _VALID_YAML.replace("test-agent", "refined-agent")
        response = f"Updated the name.\n\n```yaml\n{updated_yaml}```"
        mock_get_agent.return_value = _make_fake_agent(response)

        session = BuilderSession()
        session._yaml_text = _VALID_YAML

        turn = session.refine("change name to refined-agent", "openai")
        assert "refined-agent" in turn.yaml_text

    @patch("initrunner.services.agent_builder.BuilderSession._get_agent")
    def test_refine_preserves_message_history(self, mock_get_agent):
        response = f"```yaml\n{_VALID_YAML}```"
        agent = _make_fake_agent(response)
        mock_get_agent.return_value = agent

        session = BuilderSession()
        session._yaml_text = _VALID_YAML
        session._messages = [{"role": "user", "content": "initial"}]  # type: ignore[list-item]

        session.refine("add memory", "openai")
        call_args = agent.run_sync.call_args
        assert call_args[1].get("message_history") is not None


# ---------------------------------------------------------------------------
# BuilderSession -- save
# ---------------------------------------------------------------------------


class TestBuilderSessionSave:
    def test_save_writes_file(self, tmp_path):
        session = BuilderSession()
        session._yaml_text = _VALID_YAML
        out = tmp_path / "role.yaml"

        result = session.save(out)
        assert out.exists()
        assert result.yaml_path == out
        assert result.valid is True
        assert len(result.next_steps) > 0

    def test_save_refuses_overwrite_without_force(self, tmp_path):
        session = BuilderSession()
        session._yaml_text = _VALID_YAML
        out = tmp_path / "role.yaml"
        out.write_text("existing")

        with pytest.raises(FileExistsError):
            session.save(out)

    def test_save_overwrites_with_force(self, tmp_path):
        session = BuilderSession()
        session._yaml_text = _VALID_YAML
        out = tmp_path / "role.yaml"
        out.write_text("existing")

        result = session.save(out, force=True)
        assert out.exists()
        assert result.valid is True

    def test_save_with_invalid_yaml(self, tmp_path):
        session = BuilderSession()
        session._yaml_text = "not: valid: yaml: for: role"
        out = tmp_path / "role.yaml"

        result = session.save(out)
        assert out.exists()
        assert result.valid is False
        assert len(result.issues) > 0

    def test_save_reports_omitted_assets(self, tmp_path):
        session = BuilderSession()
        session._yaml_text = _VALID_YAML
        session.omitted_assets = ["config.json", "skills/SKILL.md"]
        out = tmp_path / "role.yaml"

        result = session.save(out)
        assert result.omitted_assets == ["config.json", "skills/SKILL.md"]


# ---------------------------------------------------------------------------
# generate_role() one-shot wrapper
# ---------------------------------------------------------------------------


class TestGenerateRoleWrapper:
    @patch("initrunner.services.agent_builder.BuilderSession._get_agent")
    def test_generate_role_via_builder(self, mock_get_agent):
        response = f"```yaml\n{_VALID_YAML}```"
        mock_get_agent.return_value = _make_fake_agent(response)

        from initrunner.role_generator import generate_role

        result = generate_role("a simple chatbot", provider="openai")
        assert "test-agent" in result
        assert "apiVersion" in result
