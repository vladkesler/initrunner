"""Tests for the CLI ``new`` command."""

from __future__ import annotations

import re
import textwrap
from unittest.mock import MagicMock, patch

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
# --list-templates
# ---------------------------------------------------------------------------

_ROLE_TEMPLATES = {"basic", "rag", "daemon", "memory", "ollama", "api", "telegram", "discord"}


class TestListTemplates:
    def test_list_templates_exits_zero(self):
        result = runner.invoke(app, ["new", "--list-templates"])
        assert result.exit_code == 0

    def test_list_templates_shows_all_role_templates(self):
        result = runner.invoke(app, ["new", "--list-templates"])
        for name in _ROLE_TEMPLATES:
            assert name in result.output

    def test_list_templates_excludes_non_role(self):
        result = runner.invoke(app, ["new", "--list-templates"])
        # blank is a separate flag; tool/skill are scaffolds
        assert "blank" not in result.output.lower().split()
        assert "tool" not in result.output.lower().split()
        assert "skill" not in result.output.lower().split()

    def test_list_templates_in_help(self):
        result = runner.invoke(app, ["new", "--help"])
        plain = re.sub(r"\x1b\[[0-9;]*m", "", result.output)
        assert "--list-templates" in plain


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
        assert "Usage:" in result.output

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


# ---------------------------------------------------------------------------
# Provider/model resolution -- run.yaml precedence
# ---------------------------------------------------------------------------


class TestProviderResolution:
    """init new should respect run.yaml over env-var auto-detection."""

    def test_run_yaml_overrides_env_detection(self, tmp_path, monkeypatch):
        """run.yaml provider takes precedence over higher-priority env vars."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-stale-key")
        monkeypatch.delenv("INITRUNNER_MODEL", raising=False)

        # Patch detect_default_model to simulate run.yaml returning openai
        with patch(
            "initrunner.agent.loader.detect_default_model",
            return_value=("openai", "gpt-5-mini", None, None, "run_yaml"),
        ):
            output = tmp_path / "role.yaml"
            result = runner.invoke(
                app,
                ["new", "--blank", "--output", str(output), "--no-refine"],
            )
        assert result.exit_code == 0
        content = output.read_text()
        assert "openai" in content

    def test_cli_flags_override_run_yaml(self, tmp_path, monkeypatch):
        """Explicit --provider flag overrides run.yaml."""
        monkeypatch.delenv("INITRUNNER_MODEL", raising=False)

        with patch(
            "initrunner.agent.loader.detect_default_model",
            return_value=("openai", "gpt-5-mini", None, None, "run_yaml"),
        ):
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

    def test_base_url_injected_into_yaml(self, tmp_path, monkeypatch):
        """base_url from run.yaml is injected into generated YAML."""
        monkeypatch.delenv("INITRUNNER_MODEL", raising=False)

        with patch(
            "initrunner.agent.loader.detect_default_model",
            return_value=(
                "openai",
                "gpt-5-mini",
                "https://openrouter.ai/api/v1",
                "OPENROUTER_API_KEY",
                "run_yaml",
            ),
        ):
            output = tmp_path / "role.yaml"
            result = runner.invoke(
                app,
                ["new", "--blank", "--output", str(output), "--no-refine"],
            )
        assert result.exit_code == 0
        content = output.read_text()
        assert "https://openrouter.ai/api/v1" in content
        assert "OPENROUTER_API_KEY" in content


# ---------------------------------------------------------------------------
# 401 error handling
# ---------------------------------------------------------------------------


class TestAuthErrorHandling:
    """401 errors should show clear guidance, not raw tracebacks."""

    def test_seed_401_shows_auth_message(self, tmp_path, monkeypatch):
        """A 401 during seed shows authentication guidance."""
        from pydantic_ai.exceptions import ModelHTTPError

        monkeypatch.delenv("INITRUNNER_MODEL", raising=False)

        session, _ = _mock_builder_session()
        session.seed_description.side_effect = ModelHTTPError(
            status_code=401, model_name="test-model", body=None
        )

        with (
            patch("initrunner.services.agent_builder.BuilderSession", return_value=session),
            patch(
                "initrunner.agent.loader.detect_default_model",
                return_value=("openai", "gpt-5-mini", None, None, "run_yaml"),
            ),
        ):
            output = tmp_path / "role.yaml"
            result = runner.invoke(
                app,
                ["new", "a chatbot", "--output", str(output), "--no-refine"],
            )
        assert result.exit_code == 1
        plain = re.sub(r"\x1b\[[0-9;]*m", "", result.output)
        assert "authentication failed" in plain.lower()
        assert "initrunner setup" in plain

    def test_seed_other_http_error_shows_status(self, tmp_path, monkeypatch):
        """Non-401 HTTP errors show the status code."""
        from pydantic_ai.exceptions import ModelHTTPError

        monkeypatch.delenv("INITRUNNER_MODEL", raising=False)

        session, _ = _mock_builder_session()
        session.seed_description.side_effect = ModelHTTPError(
            status_code=429, model_name="test-model", body=None
        )

        with (
            patch("initrunner.services.agent_builder.BuilderSession", return_value=session),
            patch(
                "initrunner.agent.loader.detect_default_model",
                return_value=("openai", "gpt-5-mini", None, None, "run_yaml"),
            ),
        ):
            output = tmp_path / "role.yaml"
            result = runner.invoke(
                app,
                ["new", "a chatbot", "--output", str(output), "--no-refine"],
            )
        assert result.exit_code == 1
        plain = re.sub(r"\x1b\[[0-9;]*m", "", result.output)
        assert "429" in plain
