"""Tests for the CLI ``new`` command."""

from __future__ import annotations

import textwrap
from unittest.mock import MagicMock

from typer.testing import CliRunner

from initrunner.cli.main import app

runner = CliRunner()

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


def _mock_builder_session():
    """Create a mock BuilderSession that returns valid YAML."""
    from initrunner.services.agent_builder import TurnResult

    turn = TurnResult(
        explanation="Generated from your description.",
        yaml_text=_VALID_YAML,
        issues=[],
    )

    session = MagicMock()
    session.seed_blank.return_value = turn
    session.seed_template.return_value = turn
    session.seed_description.return_value = turn
    session.seed_from_file.return_value = turn
    session.seed_from_example.return_value = turn
    session.omitted_assets = []
    session.role = MagicMock()
    session.role.metadata.name = "test-agent"
    return session, turn


# ---------------------------------------------------------------------------
# Seed mode mutual exclusivity
# ---------------------------------------------------------------------------


class TestNewSeedModes:
    def test_multiple_seed_modes_errors(self, tmp_path):
        output = tmp_path / "role.yaml"
        result = runner.invoke(
            app,
            ["new", "a chatbot", "--blank", "--output", str(output), "--no-refine"],
        )
        assert result.exit_code == 1
        assert "at most one" in result.output.lower()

    def test_description_and_template_errors(self, tmp_path):
        output = tmp_path / "role.yaml"
        result = runner.invoke(
            app,
            ["new", "a chatbot", "--template", "rag", "--output", str(output), "--no-refine"],
        )
        assert result.exit_code == 1

    def test_description_and_from_errors(self, tmp_path):
        output = tmp_path / "role.yaml"
        result = runner.invoke(
            app,
            ["new", "a chatbot", "--from", "hello-world", "--output", str(output), "--no-refine"],
        )
        assert result.exit_code == 1


# ---------------------------------------------------------------------------
# Blank seed
# ---------------------------------------------------------------------------


class TestNewBlank:
    def test_blank_creates_file(self, tmp_path):
        output = tmp_path / "role.yaml"
        result = runner.invoke(
            app,
            ["new", "--blank", "--output", str(output), "--no-refine"],
        )
        assert result.exit_code == 0
        assert output.exists()
        content = output.read_text()
        assert "my-agent" in content
        assert "initrunner/v1" in content

    def test_blank_with_provider(self, tmp_path):
        output = tmp_path / "role.yaml"
        result = runner.invoke(
            app,
            [
                "new",
                "--blank",
                "--provider",
                "anthropic",
                "--output",
                str(output),
                "--no-refine",
            ],
        )
        assert result.exit_code == 0
        content = output.read_text()
        assert "anthropic" in content


# ---------------------------------------------------------------------------
# Template seed
# ---------------------------------------------------------------------------


class TestNewTemplate:
    def test_template_rag(self, tmp_path):
        output = tmp_path / "role.yaml"
        result = runner.invoke(
            app,
            ["new", "--template", "rag", "--output", str(output), "--no-refine"],
        )
        assert result.exit_code == 0
        content = output.read_text()
        assert "ingest" in content

    def test_template_daemon(self, tmp_path):
        output = tmp_path / "role.yaml"
        result = runner.invoke(
            app,
            ["new", "--template", "daemon", "--output", str(output), "--no-refine"],
        )
        assert result.exit_code == 0
        content = output.read_text()
        assert "triggers" in content

    def test_template_memory(self, tmp_path):
        output = tmp_path / "role.yaml"
        result = runner.invoke(
            app,
            ["new", "--template", "memory", "--output", str(output), "--no-refine"],
        )
        assert result.exit_code == 0
        content = output.read_text()
        assert "memory" in content

    def test_template_invalid(self, tmp_path):
        output = tmp_path / "role.yaml"
        result = runner.invoke(
            app,
            ["new", "--template", "nonexistent", "--output", str(output), "--no-refine"],
        )
        assert result.exit_code == 1


# ---------------------------------------------------------------------------
# --no-refine
# ---------------------------------------------------------------------------


class TestNewNoRefine:
    def test_no_refine_skips_loop(self, tmp_path):
        output = tmp_path / "role.yaml"
        result = runner.invoke(
            app,
            ["new", "--blank", "--output", str(output), "--no-refine"],
        )
        assert result.exit_code == 0
        assert output.exists()
        # Should show next steps
        assert "Next steps" in result.output


# ---------------------------------------------------------------------------
# Overwrite handling
# ---------------------------------------------------------------------------


class TestNewOverwrite:
    def test_refuses_overwrite_without_force(self, tmp_path):
        output = tmp_path / "role.yaml"
        output.write_text("existing")
        runner.invoke(
            app,
            ["new", "--blank", "--output", str(output), "--no-refine"],
            input="n\n",
        )
        # User said no to overwrite
        assert output.read_text() == "existing"

    def test_force_overwrites(self, tmp_path):
        output = tmp_path / "role.yaml"
        output.write_text("existing")
        result = runner.invoke(
            app,
            ["new", "--blank", "--output", str(output), "--no-refine", "--force"],
        )
        assert result.exit_code == 0
        assert output.read_text() != "existing"


# ---------------------------------------------------------------------------
# Command surface: init and create are gone, new is registered
# ---------------------------------------------------------------------------


class TestCommandSurface:
    def test_init_not_registered(self):
        result = runner.invoke(app, ["init"])
        # Should fail -- not a recognized command
        assert result.exit_code != 0

    def test_create_not_registered(self):
        result = runner.invoke(app, ["create", "some description"])
        assert result.exit_code != 0

    def test_new_is_registered(self):
        result = runner.invoke(app, ["new", "--help"])
        assert result.exit_code == 0
        assert "Create a new agent" in result.output

    def test_skill_new_registered(self):
        result = runner.invoke(app, ["skill", "new", "--help"])
        assert result.exit_code == 0
        assert "Scaffold" in result.output


# ---------------------------------------------------------------------------
# Zero-arg behavior
# ---------------------------------------------------------------------------


class TestZeroArg:
    def test_non_tty_shows_help(self):
        """Non-TTY (piped) should show help text."""
        result = runner.invoke(app, [])
        assert result.exit_code == 0
        assert "Commands" in result.output

    def test_new_command_in_help(self):
        """The 'new' command should appear in help output."""
        result = runner.invoke(app, ["--help"])
        assert "new" in result.output

    def test_init_not_in_help(self):
        """The old 'init' command should not appear in help output."""
        result = runner.invoke(app, ["--help"])
        # Check for 'init' as a command, not as substring of other words
        lines = result.output.split("\n")
        command_lines = [line.strip() for line in lines if line.strip().startswith("init ")]
        assert len(command_lines) == 0

    def test_create_not_in_help(self):
        """The old 'create' command should not appear in help output."""
        result = runner.invoke(app, ["--help"])
        lines = result.output.split("\n")
        command_lines = [line.strip() for line in lines if line.strip().startswith("create ")]
        assert len(command_lines) == 0
