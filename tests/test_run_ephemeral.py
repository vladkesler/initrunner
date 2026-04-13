"""Tests for ephemeral mode (no role file) in the run command."""

from __future__ import annotations

from unittest.mock import patch

from typer.testing import CliRunner

from initrunner.cli.main import app

runner = CliRunner()


class TestEphemeralFlagValidation:
    """Ephemeral-incompatible flags should error without a role file."""

    def test_daemon_rejected(self):
        result = runner.invoke(app, ["run", "--daemon"])
        assert result.exit_code == 1
        assert "daemon" in result.output
        assert "not supported without a role file" in result.output

    def test_serve_rejected(self):
        result = runner.invoke(app, ["run", "--serve"])
        assert result.exit_code == 1
        assert "serve" in result.output
        assert "not supported without a role file" in result.output

    def test_autonomous_rejected(self):
        result = runner.invoke(app, ["run", "-a", "-p", "hello"])
        assert result.exit_code == 1
        assert "--autonomous" in result.output

    def test_dry_run_rejected(self):
        result = runner.invoke(app, ["run", "--dry-run", "-p", "hello"])
        assert result.exit_code == 1
        assert "--dry-run" in result.output

    def test_save_rejected(self):
        result = runner.invoke(app, ["run", "--save", "/tmp/x", "-p", "hello"])
        assert result.exit_code == 1
        assert "--save" in result.output

    def test_resume_rejected_for_one_shot(self):
        """--resume with -p (no -i) should error."""
        result = runner.invoke(app, ["run", "--resume", "-p", "hello"])
        assert result.exit_code == 1
        assert "--resume" in result.output


class TestEphemeralDispatch:
    """Test ephemeral mode dispatch paths."""

    @patch("initrunner.cli._ephemeral.dispatch_ephemeral")
    def test_no_args_dispatches_ephemeral(self, mock_dispatch):
        result = runner.invoke(app, ["run"])
        assert result.exit_code == 0
        mock_dispatch.assert_called_once()

    @patch("initrunner.cli._ephemeral.dispatch_ephemeral")
    def test_prompt_dispatches_ephemeral(self, mock_dispatch):
        result = runner.invoke(app, ["run", "-p", "hello"])
        assert result.exit_code == 0
        mock_dispatch.assert_called_once()
        kwargs = mock_dispatch.call_args[1]
        assert kwargs["prompt"] == "hello"

    @patch("initrunner.cli._ephemeral.dispatch_ephemeral")
    def test_bot_flag_dispatches_ephemeral(self, mock_dispatch):
        result = runner.invoke(app, ["run", "--bot", "telegram"])
        assert result.exit_code == 0
        mock_dispatch.assert_called_once()
        kwargs = mock_dispatch.call_args[1]
        assert kwargs["bot"] == "telegram"

    @patch("initrunner.cli._ephemeral.dispatch_ephemeral")
    def test_tool_profile_passed(self, mock_dispatch):
        result = runner.invoke(app, ["run", "--tool-profile", "all"])
        assert result.exit_code == 0
        kwargs = mock_dispatch.call_args[1]
        assert kwargs["tool_profile"] == "all"


class TestRoleIncompatibleFlags:
    """Ephemeral-only flags should error when a role file is given."""

    def test_tool_profile_rejected_with_role(self, tmp_path):
        role = tmp_path / "role.yaml"
        role.write_text(
            "apiVersion: initrunner/v1\nkind: Agent\nmetadata:\n  name: t\n"
            "spec:\n  role: test\n  model:\n    provider: openai\n    name: gpt-5-mini\n"
        )
        result = runner.invoke(app, ["run", str(role), "--tool-profile", "all"])
        assert result.exit_code == 1
        assert "--tool-profile" in result.output

    def test_provider_rejected_with_role(self, tmp_path):
        role = tmp_path / "role.yaml"
        role.write_text(
            "apiVersion: initrunner/v1\nkind: Agent\nmetadata:\n  name: t\n"
            "spec:\n  role: test\n  model:\n    provider: openai\n    name: gpt-5-mini\n"
        )
        result = runner.invoke(app, ["run", str(role), "--provider", "anthropic"])
        assert result.exit_code == 1
        assert "--provider" in result.output


class TestSenseValidation:
    """--sense should reject daemon/serve/bot modes."""

    def test_sense_rejects_daemon(self):
        result = runner.invoke(app, ["run", "--sense", "-p", "hello", "--daemon"])
        assert result.exit_code == 1

    def test_sense_rejects_serve(self):
        result = runner.invoke(app, ["run", "--sense", "-p", "hello", "--serve"])
        assert result.exit_code == 1

    def test_sense_rejects_bot(self):
        result = runner.invoke(app, ["run", "--sense", "-p", "hello", "--bot", "telegram"])
        assert result.exit_code == 1


class TestListFlags:
    """Test --list and --list-tools."""

    def test_list_shows_starters(self):
        result = runner.invoke(app, ["run", "--list"])
        assert result.exit_code == 0
        assert "Starter Agents" in result.output

    def test_list_tools_shows_tools(self):
        result = runner.invoke(app, ["run", "--list-tools"])
        assert result.exit_code == 0
        assert "Available extra tools" in result.output


class TestExplainProfiles:
    """--explain-profiles should show profile breakdown."""

    def test_explain_profiles_shows_all_profiles(self):
        result = runner.invoke(app, ["run", "--explain-profiles"])
        assert result.exit_code == 0
        assert "none" in result.output
        assert "minimal" in result.output
        assert "all" in result.output
        assert "datetime" in result.output
        assert "web_reader" in result.output

    def test_explain_profiles_exits_cleanly_with_other_flags(self):
        """--explain-profiles should exit before validation runs."""
        result = runner.invoke(app, ["run", "--explain-profiles", "--daemon"])
        assert result.exit_code == 0
        assert "Tool profiles" in result.output


class TestEphemeralSenseOnlyFlags:
    """--confirm-role and --role-dir should error without --sense in ephemeral mode."""

    def test_confirm_role_without_sense_rejected(self):
        result = runner.invoke(app, ["run", "--confirm-role", "-p", "hi"])
        assert result.exit_code == 1
        assert "--confirm-role" in result.output
        assert "--sense" in result.output

    def test_role_dir_without_sense_rejected(self):
        result = runner.invoke(app, ["run", "--role-dir", "/tmp", "-p", "hi"])
        assert result.exit_code == 1
        assert "--role-dir" in result.output
        assert "--sense" in result.output


class TestEphemeralModeSpecificFlags:
    """Serve-only and bot-only flags should error in ephemeral mode without their parent."""

    def test_api_key_without_serve_rejected(self):
        result = runner.invoke(app, ["run", "--api-key", "secret"])
        assert result.exit_code == 1
        assert "--api-key" in result.output
        assert "--serve" in result.output

    def test_allowed_users_without_bot_rejected(self):
        result = runner.invoke(app, ["run", "--allowed-users", "alice"])
        assert result.exit_code == 1
        assert "--allowed-users" in result.output
        assert "--bot" in result.output


class TestChatRemoved:
    """chat command should not exist."""

    def test_chat_command_gone(self):
        result = runner.invoke(app, ["chat"])
        assert result.exit_code != 0
