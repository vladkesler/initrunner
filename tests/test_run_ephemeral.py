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

    @patch("initrunner.cli._ephemeral.dispatch_ephemeral")
    def test_tool_profile_none_passed(self, mock_dispatch):
        result = runner.invoke(app, ["run", "--tool-profile", "none"])
        assert result.exit_code == 0
        assert mock_dispatch.call_args[1]["tool_profile"] == "none"


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


def _attached_types(kwargs: dict) -> list[str]:
    return [t["type"] for t in kwargs["attached_tools"]]


class TestAttachedToolsHonorProfile:
    """dispatch_ephemeral must attach the selected profile, not the catalog."""

    @patch("initrunner.cli._ephemeral.dispatch_ephemeral_repl")
    @patch("initrunner.run_config.load_run_config")
    def test_default_minimal(self, mock_cfg, mock_repl):
        from initrunner.run_config import RunConfig

        mock_cfg.return_value = RunConfig(provider="openai", model="gpt-5-mini")
        from initrunner.cli._ephemeral import dispatch_ephemeral

        dispatch_ephemeral(prompt="hello")
        types = _attached_types(mock_repl.call_args[1])
        assert types == ["datetime", "web_reader"]

    @patch("initrunner.cli._ephemeral.dispatch_ephemeral_repl")
    @patch("initrunner.run_config.load_run_config")
    def test_none_is_empty(self, mock_cfg, mock_repl):
        from initrunner.run_config import RunConfig

        mock_cfg.return_value = RunConfig(provider="openai", model="gpt-5-mini")
        from initrunner.cli._ephemeral import dispatch_ephemeral

        dispatch_ephemeral(prompt="hello", tool_profile="none")
        assert mock_repl.call_args[1]["attached_tools"] == []

    @patch("initrunner.cli._ephemeral.dispatch_ephemeral_repl")
    @patch("initrunner.run_config.load_run_config")
    def test_all_includes_exec_tools(self, mock_cfg, mock_repl):
        from initrunner.run_config import RunConfig

        mock_cfg.return_value = RunConfig(provider="openai", model="gpt-5-mini")
        from initrunner.cli._ephemeral import dispatch_ephemeral

        dispatch_ephemeral(prompt="hello", tool_profile="all")
        types = set(_attached_types(mock_repl.call_args[1]))
        assert {"python", "shell", "datetime", "web_reader"} <= types

    @patch("initrunner.cli._ephemeral.dispatch_ephemeral_repl")
    @patch("initrunner.run_config.load_run_config")
    def test_minimal_plus_python_extra(self, mock_cfg, mock_repl):
        from initrunner.run_config import RunConfig

        mock_cfg.return_value = RunConfig(provider="openai", model="gpt-5-mini")
        from initrunner.cli._ephemeral import dispatch_ephemeral

        dispatch_ephemeral(prompt="hello", extra_tools=["python"])
        assert _attached_types(mock_repl.call_args[1]) == [
            "datetime",
            "web_reader",
            "python",
        ]

    @patch("initrunner.cli._ephemeral.dispatch_ephemeral_repl")
    @patch("initrunner.run_config.load_run_config")
    def test_run_yaml_extras_merge_onto_profile(self, mock_cfg, mock_repl):
        from initrunner.run_config import RunConfig

        mock_cfg.return_value = RunConfig(
            provider="openai",
            model="gpt-5-mini",
            tool_profile="minimal",
            tools=["git"],
        )
        from initrunner.cli._ephemeral import dispatch_ephemeral

        dispatch_ephemeral(prompt="hello")
        assert _attached_types(mock_repl.call_args[1]) == [
            "datetime",
            "web_reader",
            "git",
        ]

    @patch("initrunner.cli._ephemeral.dispatch_ephemeral_bot")
    @patch("initrunner.run_config.load_run_config")
    def test_bot_gets_attached_profile(self, mock_cfg, mock_bot):
        from initrunner.run_config import RunConfig

        mock_cfg.return_value = RunConfig(provider="openai", model="gpt-5-mini")
        from initrunner.cli._ephemeral import dispatch_ephemeral

        dispatch_ephemeral(bot="telegram", tool_profile="none")
        assert mock_bot.call_args[1]["attached_tools"] == []


class TestCheckProfileEnvsSelectedOnly:
    def test_missing_slack_silent_under_minimal(self, capsys):
        from initrunner.cli._ephemeral import check_profile_envs

        with patch(
            "initrunner.services.providers.check_tool_envs",
            return_value={},
        ) as mock_check:
            skipped = check_profile_envs({"datetime", "web_reader"})

        mock_check.assert_called_once_with({"datetime", "web_reader"})
        assert skipped == set()
        assert "Skipping tool" not in capsys.readouterr().out

    def test_prints_skip_only_for_selected_missing(self, capsys):
        from initrunner.cli._ephemeral import check_profile_envs

        with patch(
            "initrunner.services.providers.check_tool_envs",
            return_value={"slack": ["SLACK_WEBHOOK_URL"]},
        ):
            skipped = check_profile_envs({"slack"})

        assert skipped == {"slack"}
        assert "slack" in capsys.readouterr().out


class TestIngestRebuildKeepsAttached:
    @patch("initrunner.agent.loader.build_agent")
    @patch("initrunner.runner.run_single")
    @patch("initrunner.cli._ephemeral.run_ephemeral_ingest")
    def test_empty_stays_empty(self, _ingest, mock_single, _build_agent):
        from initrunner.cli._ephemeral import dispatch_ephemeral_repl
        from initrunner.services.providers import build_ephemeral_role

        captured: dict = {}

        def _capture(*args, **kwargs):
            captured.update(kwargs)
            return build_ephemeral_role("openai", "gpt-5-mini", **kwargs)

        with (
            patch(
                "initrunner.services.providers.build_quick_chat_role_sync",
                return_value=(
                    build_ephemeral_role("openai", "gpt-5-mini", tools=[]),
                    "openai",
                    "gpt-5-mini",
                ),
            ),
            patch(
                "initrunner.services.providers.build_ephemeral_role",
                side_effect=_capture,
            ),
            patch("initrunner.cli._helpers.ephemeral_context") as mock_ctx,
        ):
            mock_ctx.return_value.__enter__.return_value = (
                None,
                None,
                None,
                None,
            )
            mock_ctx.return_value.__exit__.return_value = False
            mock_single.return_value = None
            dispatch_ephemeral_repl(
                provider="openai",
                model="gpt-5-mini",
                prompt="hello",
                interactive=False,
                attached_tools=[],
                audit_db=None,
                no_audit=True,
                ingest_paths=["./docs"],
            )

        assert captured.get("tools") == []


class TestSandboxWarningsFollowAttachedTools:
    def test_minimal_role_does_not_warn(self, caplog, monkeypatch):
        import logging

        from initrunner.agent.loader import build_agent
        from initrunner.services.providers import build_quick_chat_role_sync

        monkeypatch.setattr(logging.getLogger("initrunner"), "propagate", True)
        caplog.set_level(logging.WARNING, logger="initrunner")

        with patch("initrunner.services.providers._load_env"):
            role, _, _ = build_quick_chat_role_sync(
                provider="openai",
                model="gpt-5-mini",
                tool_defs=None,
                with_memory=False,
            )

        with patch("initrunner.agent.loader.require_provider"):
            build_agent(role)

        text = caplog.text
        assert "no sandbox" not in text
        assert "allowed_commands" not in text

    def test_all_role_warns_for_exec_tools(self, caplog, monkeypatch):
        import logging

        from initrunner.agent.loader import build_agent
        from initrunner.services.providers import (
            TOOL_PROFILES,
            build_quick_chat_role_sync,
        )

        monkeypatch.setattr(logging.getLogger("initrunner"), "propagate", True)
        caplog.set_level(logging.WARNING, logger="initrunner")

        with (
            patch("initrunner.services.providers._load_env"),
            patch("initrunner.services.providers.check_tool_envs", return_value={}),
        ):
            role, _, _ = build_quick_chat_role_sync(
                provider="openai",
                model="gpt-5-mini",
                tool_defs=list(TOOL_PROFILES["all"]),
                with_memory=False,
            )

        with patch("initrunner.agent.loader.require_provider"):
            build_agent(role)

        assert "no sandbox" in caplog.text
