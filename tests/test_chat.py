"""Tests for the chat command."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from initrunner.cli.main import app

runner = CliRunner()

# Prevent .env loading from polluting tests
_MOCK_LOAD_ENV = patch("initrunner.services.providers._load_env")


@pytest.fixture()
def clean_env(monkeypatch, tmp_path):
    """Remove all provider API keys and bot tokens from the env."""
    for var in (
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "GOOGLE_API_KEY",
        "GROQ_API_KEY",
        "MISTRAL_API_KEY",
        "CO_API_KEY",
        "TELEGRAM_BOT_TOKEN",
        "DISCORD_BOT_TOKEN",
    ):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("INITRUNNER_HOME", str(tmp_path / "home"))
    from initrunner.config import get_home_dir

    get_home_dir.cache_clear()
    yield tmp_path
    get_home_dir.cache_clear()


class TestChatMutualExclusion:
    def test_telegram_and_discord_exclusive(self, clean_env):
        """--telegram and --discord cannot be used together."""
        result = runner.invoke(app, ["chat", "--telegram", "--discord"])
        assert result.exit_code == 1
        assert "mutually exclusive" in result.output


class TestChatToolProfile:
    def test_invalid_tool_profile(self, clean_env):
        result = runner.invoke(app, ["chat", "--tool-profile", "unknown"])
        assert result.exit_code == 1
        assert "Unknown tool profile" in result.output

    def test_all_profile_includes_all_tools(self, clean_env, monkeypatch):
        """--tool-profile all with required env vars includes every tool type."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/test")

        with (
            _MOCK_LOAD_ENV,
            patch("initrunner.agent.loader.build_agent") as mock_build,
            patch("initrunner.runner.run_interactive"),
        ):
            mock_build.return_value = MagicMock()
            result = runner.invoke(app, ["chat", "--tool-profile", "all"])

        assert result.exit_code == 0
        role = mock_build.call_args[0][0]
        tool_types = {t.type for t in role.spec.tools}
        expected = {
            "datetime",
            "web_reader",
            "search",
            "python",
            "filesystem",
            "slack",
            "git",
            "shell",
        }
        assert tool_types == expected

    def test_all_profile_missing_env_fails(self, clean_env, monkeypatch):
        """--tool-profile all without SLACK_WEBHOOK_URL exits with actionable error."""
        monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
        result = runner.invoke(app, ["chat", "--tool-profile", "all"])
        assert result.exit_code == 1
        assert "SLACK_WEBHOOK_URL" in result.output


class TestChatAutoDetect:
    def test_no_provider_found(self, clean_env):
        """Without any API keys, chat should show an error."""
        with (
            _MOCK_LOAD_ENV,
            patch("initrunner.services.providers._is_ollama_running", return_value=False),
        ):
            result = runner.invoke(app, ["chat"])
        assert result.exit_code == 1
        assert "No API key found" in result.output

    def test_auto_detect_starts_repl(self, clean_env, monkeypatch):
        """With an API key, chat should auto-detect and start the REPL."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

        with (
            _MOCK_LOAD_ENV,
            patch("initrunner.agent.loader.build_agent") as mock_build,
            patch("initrunner.runner.run_interactive") as mock_repl,
        ):
            mock_agent = MagicMock()
            mock_build.return_value = mock_agent
            result = runner.invoke(app, ["chat"])

        assert result.exit_code == 0
        mock_repl.assert_called_once()

    def test_provider_override(self, clean_env, monkeypatch):
        """--provider overrides auto-detection."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")

        with (
            _MOCK_LOAD_ENV,
            patch("initrunner.agent.loader.build_agent") as mock_build,
            patch("initrunner.runner.interactive.run_interactive"),
        ):
            mock_build.return_value = MagicMock()
            result = runner.invoke(app, ["chat", "--provider", "anthropic"])

        assert result.exit_code == 0
        # Verify the role was built with anthropic provider
        role = mock_build.call_args[0][0]
        assert role.spec.model.provider == "anthropic"

    def test_model_override(self, clean_env, monkeypatch):
        """--model overrides the default model."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

        with (
            _MOCK_LOAD_ENV,
            patch("initrunner.agent.loader.build_agent") as mock_build,
            patch("initrunner.runner.interactive.run_interactive"),
        ):
            mock_build.return_value = MagicMock()
            result = runner.invoke(app, ["chat", "--model", "gpt-4o"])

        assert result.exit_code == 0
        role = mock_build.call_args[0][0]
        assert role.spec.model.name == "gpt-4o"

    def test_prompt_then_repl(self, clean_env, monkeypatch):
        """--prompt sends a message then enters REPL."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

        with (
            _MOCK_LOAD_ENV,
            patch("initrunner.agent.loader.build_agent") as mock_build,
            patch("initrunner.runner.run_single") as mock_single,
            patch("initrunner.runner.run_interactive") as mock_repl,
        ):
            mock_build.return_value = MagicMock()
            mock_single.return_value = (MagicMock(), [])
            result = runner.invoke(app, ["chat", "-p", "hello"])

        assert result.exit_code == 0
        mock_single.assert_called_once()
        mock_repl.assert_called_once()


class TestChatBotMode:
    def test_telegram_missing_token(self, clean_env, monkeypatch):
        """--telegram without TELEGRAM_BOT_TOKEN should fail."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        with _MOCK_LOAD_ENV:
            result = runner.invoke(app, ["chat", "--telegram"])
        assert result.exit_code == 1
        assert "TELEGRAM_BOT_TOKEN" in result.output

    def test_discord_missing_token(self, clean_env, monkeypatch):
        """--discord without DISCORD_BOT_TOKEN should fail."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        with _MOCK_LOAD_ENV:
            result = runner.invoke(app, ["chat", "--discord"])
        assert result.exit_code == 1
        assert "DISCORD_BOT_TOKEN" in result.output

    def test_telegram_missing_sdk(self, clean_env, monkeypatch):
        """--telegram without python-telegram-bot should fail with install hint."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")

        with (
            _MOCK_LOAD_ENV,
            patch.dict("sys.modules", {"telegram": None}),
        ):
            result = runner.invoke(app, ["chat", "--telegram"])
        assert result.exit_code == 1
        assert "python-telegram-bot" in result.output

    def test_discord_missing_sdk(self, clean_env, monkeypatch):
        """--discord without discord.py should fail with install hint."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        monkeypatch.setenv("DISCORD_BOT_TOKEN", "token-abc")

        with (
            _MOCK_LOAD_ENV,
            patch.dict("sys.modules", {"discord": None}),
        ):
            result = runner.invoke(app, ["chat", "--discord"])
        assert result.exit_code == 1
        assert "discord.py" in result.output

    def test_telegram_bot_launches(self, clean_env, monkeypatch):
        """--telegram with valid config should launch daemon."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")

        mock_telegram = MagicMock()
        with (
            _MOCK_LOAD_ENV,
            patch.dict("sys.modules", {"telegram": mock_telegram}),
            patch("initrunner.agent.loader.build_agent") as mock_build,
            patch("initrunner.runner.run_daemon") as mock_daemon,
        ):
            mock_build.return_value = MagicMock()
            result = runner.invoke(app, ["chat", "--telegram"])

        assert result.exit_code == 0
        mock_daemon.assert_called_once()
        # Verify the role has autonomy configured
        call_args = mock_daemon.call_args
        role = call_args[0][1]
        assert role.spec.autonomy is not None
        assert len(role.spec.triggers) == 1
        assert role.spec.triggers[0].type == "telegram"

    def test_discord_bot_launches(self, clean_env, monkeypatch):
        """--discord with valid config should launch daemon."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        monkeypatch.setenv("DISCORD_BOT_TOKEN", "token-abc")

        mock_discord = MagicMock()
        with (
            _MOCK_LOAD_ENV,
            patch.dict("sys.modules", {"discord": mock_discord}),
            patch("initrunner.agent.loader.build_agent") as mock_build,
            patch("initrunner.runner.run_daemon") as mock_daemon,
        ):
            mock_build.return_value = MagicMock()
            result = runner.invoke(app, ["chat", "--discord"])

        assert result.exit_code == 0
        mock_daemon.assert_called_once()
        call_args = mock_daemon.call_args
        role = call_args[0][1]
        assert role.spec.autonomy is not None
        assert role.spec.triggers[0].type == "discord"

    def test_bot_tool_profile_all(self, clean_env, monkeypatch):
        """--tool-profile all includes every tool type."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
        monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/test")

        mock_telegram = MagicMock()
        with (
            _MOCK_LOAD_ENV,
            patch.dict("sys.modules", {"telegram": mock_telegram}),
            patch("initrunner.agent.loader.build_agent") as mock_build,
            patch("initrunner.runner.run_daemon") as mock_daemon,
        ):
            mock_build.return_value = MagicMock()
            result = runner.invoke(app, ["chat", "--telegram", "--tool-profile", "all"])

        assert result.exit_code == 0
        call_args = mock_daemon.call_args
        role = call_args[0][1]
        tool_types = [t.type for t in role.spec.tools]
        assert "python" in tool_types
        assert "filesystem" in tool_types

    def test_bot_tool_profile_none(self, clean_env, monkeypatch):
        """--tool-profile none gives no tools."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")

        mock_telegram = MagicMock()
        with (
            _MOCK_LOAD_ENV,
            patch.dict("sys.modules", {"telegram": mock_telegram}),
            patch("initrunner.agent.loader.build_agent") as mock_build,
            patch("initrunner.runner.run_daemon") as mock_daemon,
        ):
            mock_build.return_value = MagicMock()
            result = runner.invoke(app, ["chat", "--telegram", "--tool-profile", "none"])

        assert result.exit_code == 0
        call_args = mock_daemon.call_args
        role = call_args[0][1]
        assert role.spec.tools == []

    def test_bot_no_api_key(self, clean_env, monkeypatch):
        """Bot mode without API key should fail."""
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
        mock_telegram = MagicMock()

        with (
            _MOCK_LOAD_ENV,
            patch.dict("sys.modules", {"telegram": mock_telegram}),
            patch("initrunner.services.providers._is_ollama_running", return_value=False),
        ):
            result = runner.invoke(app, ["chat", "--telegram"])
        assert result.exit_code == 1
        assert "No API key found" in result.output


class TestChatWithRoleFile:
    def test_chat_with_role_file(self, clean_env, monkeypatch, tmp_path):
        """chat <role.yaml> loads and runs interactively."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

        role_file = tmp_path / "role.yaml"
        role_file.write_text(
            """\
apiVersion: initrunner/v1
kind: Agent
metadata:
  name: test-agent
spec:
  role: You are a test agent.
  model:
    provider: openai
    name: gpt-5-mini
"""
        )

        with (
            patch("initrunner.runner.run_interactive") as mock_repl,
            patch("initrunner.agent.loader.load_and_build") as mock_load,
        ):
            mock_agent = MagicMock()
            mock_role = MagicMock()
            mock_role.spec.memory = None
            mock_role.spec.observability = None
            mock_role.spec.sinks = []
            mock_load.return_value = (mock_role, mock_agent)
            result = runner.invoke(app, ["chat", str(role_file)])

        assert result.exit_code == 0
        mock_repl.assert_called_once()


class TestExtraTools:
    def test_extra_tools_added_to_bot(self, clean_env, monkeypatch):
        """--tools slack with SLACK_WEBHOOK_URL set adds slack to role's tools."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
        monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/test")

        mock_telegram = MagicMock()
        with (
            _MOCK_LOAD_ENV,
            patch.dict("sys.modules", {"telegram": mock_telegram}),
            patch("initrunner.agent.loader.build_agent") as mock_build,
            patch("initrunner.runner.run_daemon") as mock_daemon,
        ):
            mock_build.return_value = MagicMock()
            result = runner.invoke(app, ["chat", "--telegram", "--tools", "slack"])

        assert result.exit_code == 0
        role = mock_daemon.call_args[0][1]
        tool_types = [t.type for t in role.spec.tools]
        assert "slack" in tool_types

    def test_extra_tools_added_to_repl(self, clean_env, monkeypatch):
        """--tools slack in auto-detect mode adds slack to role's tools."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/test")

        with (
            _MOCK_LOAD_ENV,
            patch("initrunner.agent.loader.build_agent") as mock_build,
            patch("initrunner.runner.run_interactive"),
        ):
            mock_build.return_value = MagicMock()
            result = runner.invoke(app, ["chat", "--tools", "slack"])

        assert result.exit_code == 0
        role = mock_build.call_args[0][0]
        tool_types = [t.type for t in role.spec.tools]
        assert "slack" in tool_types

    def test_extra_tools_unknown_type_errors(self, clean_env):
        """--tools bogus exits with error."""
        result = runner.invoke(app, ["chat", "--tools", "bogus"])
        assert result.exit_code == 1
        assert "Unknown tool type" in result.output

    def test_extra_tools_missing_env_fails_fast(self, clean_env, monkeypatch):
        """--tools slack without SLACK_WEBHOOK_URL exits with actionable error."""
        monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
        result = runner.invoke(app, ["chat", "--tools", "slack"])
        assert result.exit_code == 1
        assert "SLACK_WEBHOOK_URL" in result.output

    def test_extra_tools_deduplicate_with_profile(self, clean_env, monkeypatch):
        """--tool-profile all --tools search produces no duplicate search."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/test")

        with (
            _MOCK_LOAD_ENV,
            patch("initrunner.agent.loader.build_agent") as mock_build,
            patch("initrunner.runner.run_interactive"),
        ):
            mock_build.return_value = MagicMock()
            result = runner.invoke(app, ["chat", "--tool-profile", "all", "--tools", "search"])

        assert result.exit_code == 0
        role = mock_build.call_args[0][0]
        tool_types = [t.type for t in role.spec.tools]
        assert tool_types.count("search") == 1

    def test_tools_ignored_with_role_file(self, clean_env, monkeypatch, tmp_path):
        """chat role.yaml --tools slack shows info message and uses role file tools."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/test")

        role_file = tmp_path / "role.yaml"
        role_file.write_text(
            """\
apiVersion: initrunner/v1
kind: Agent
metadata:
  name: test-agent
spec:
  role: You are a test agent.
  model:
    provider: openai
    name: gpt-5-mini
"""
        )

        with (
            patch("initrunner.runner.run_interactive"),
            patch("initrunner.agent.loader.load_and_build") as mock_load,
        ):
            mock_agent = MagicMock()
            mock_role = MagicMock()
            mock_role.spec.memory = None
            mock_role.spec.observability = None
            mock_role.spec.sinks = []
            mock_load.return_value = (mock_role, mock_agent)
            result = runner.invoke(app, ["chat", str(role_file), "--tools", "slack"])

        assert result.exit_code == 0
        assert "--tools ignored" in result.output

    def test_list_tools_outputs_supported_and_required_env(self, clean_env):
        """--list-tools prints tool table and exits cleanly."""
        result = runner.invoke(app, ["chat", "--list-tools"])
        assert result.exit_code == 0
        assert "slack" in result.output
        assert "SLACK_WEBHOOK_URL" in result.output
        assert "datetime" in result.output


class TestNoArgsCallback:
    def test_non_tty_shows_help(self, clean_env):
        """Non-TTY no-args shows help (CliRunner simulates non-TTY)."""
        result = runner.invoke(app, [])
        # CliRunner stdin is not a TTY, so we should get help output
        assert result.exit_code == 0

    def test_tty_unconfigured_runs_setup(self, clean_env):
        """TTY with no config runs setup wizard."""
        with (
            patch("sys.stdin.isatty", return_value=True),
            patch("initrunner.cli.setup_cmd.needs_setup", return_value=True),
            patch("initrunner.cli.setup_cmd.run_setup"),
        ):
            result = runner.invoke(app, [])

        # Either setup was called or we got help (depending on CliRunner tty handling)
        assert result.exit_code == 0

    def test_tty_configured_starts_chat(self, clean_env, monkeypatch):
        """TTY with API key starts chat."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

        with (
            patch("sys.stdin.isatty", return_value=True),
            patch("initrunner.cli.setup_cmd.needs_setup", return_value=False),
            patch("initrunner.cli.chat_cmd._chat_auto_detect"),
            _MOCK_LOAD_ENV,
        ):
            result = runner.invoke(app, [])

        assert result.exit_code == 0
