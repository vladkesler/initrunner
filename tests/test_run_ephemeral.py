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

    def test_format_rejected(self):
        """--format has no effect without a role file, so it is refused."""
        result = runner.invoke(app, ["run", "--format", "json", "-p", "hello"])
        assert result.exit_code == 1
        assert "--format" in result.output

    def test_var_rejected(self):
        result = runner.invoke(app, ["run", "--var", "K=V", "-p", "hello"])
        assert result.exit_code == 1
        assert "--var" in result.output

    def test_report_rejected(self):
        result = runner.invoke(app, ["run", "--report", "out.md", "-p", "hello"])
        assert result.exit_code == 1
        assert "--report" in result.output

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
    def test_tools_passed_through(self, mock_dispatch):
        result = runner.invoke(app, ["run", "--tools", "all"])
        assert result.exit_code == 0
        assert mock_dispatch.call_args[1]["tools"] == ["all"]

    @patch("initrunner.cli._ephemeral.dispatch_ephemeral")
    def test_tools_repeatable(self, mock_dispatch):
        result = runner.invoke(app, ["run", "--tools", "minimal", "--tools", "git"])
        assert result.exit_code == 0
        assert mock_dispatch.call_args[1]["tools"] == ["minimal", "git"]


class TestRoleIncompatibleFlags:
    """Ephemeral-only flags should error when a role file is given."""

    @staticmethod
    def _role(tmp_path):
        role = tmp_path / "role.yaml"
        role.write_text(
            "apiVersion: initrunner/v1\nkind: Agent\nmetadata:\n  name: t\n"
            "spec:\n  role: test\n  model:\n    provider: openai\n    name: gpt-5-mini\n"
        )
        return role

    def test_tools_rejected_with_role(self, tmp_path):
        result = runner.invoke(app, ["run", str(self._role(tmp_path)), "--tools", "all"])
        assert result.exit_code == 1
        assert "--tools" in result.output

    def test_no_memory_rejected_with_role(self, tmp_path):
        """--no-memory is False, not None: an explicit choice, not a default."""
        result = runner.invoke(app, ["run", str(self._role(tmp_path)), "--no-memory", "-p", "hi"])
        assert result.exit_code == 1
        assert "--memory/--no-memory" in result.output

    def test_memory_rejected_with_role(self, tmp_path):
        result = runner.invoke(app, ["run", str(self._role(tmp_path)), "--memory", "-p", "hi"])
        assert result.exit_code == 1
        assert "--memory/--no-memory" in result.output

    def test_ingest_rejected_with_role(self, tmp_path):
        result = runner.invoke(app, ["run", str(self._role(tmp_path)), "--ingest", "docs/"])
        assert result.exit_code == 1
        assert "--ingest" in result.output


class TestSenseValidation:
    """--sense should reject daemon/serve/bot modes."""

    def test_sense_rejects_daemon(self):
        result = runner.invoke(app, ["run", "--sense", "-p", "hello", "--daemon"])
        assert result.exit_code == 1

    def test_sense_rejects_serve(self):
        result = runner.invoke(app, ["run", "--sense", "-p", "hello", "--serve"])
        assert result.exit_code == 1


class TestListFlags:
    """--list still lists starters; the tool listings moved into --help."""

    def test_list_shows_starters(self):
        result = runner.invoke(app, ["run", "--list"])
        assert result.exit_code == 0
        assert "Starter Agents" in result.output


class TestParseToolsFlag:
    """--tools carries a profile and/or tool types in one flag."""

    def test_profile_only(self):
        from initrunner.cli._ephemeral import parse_tools_flag

        assert parse_tools_flag(["all"]) == ("all", [])

    def test_types_only(self):
        from initrunner.cli._ephemeral import parse_tools_flag

        assert parse_tools_flag(["git", "shell"]) == (None, ["git", "shell"])

    def test_comma_separated(self):
        from initrunner.cli._ephemeral import parse_tools_flag

        assert parse_tools_flag(["all,git"]) == ("all", ["git"])

    def test_whitespace_and_duplicates_ignored(self):
        from initrunner.cli._ephemeral import parse_tools_flag

        assert parse_tools_flag([" all , git ", "git"]) == ("all", ["git"])

    def test_two_profiles_rejected(self):
        result = runner.invoke(app, ["run", "--tools", "all", "--tools", "minimal", "-p", "hi"])
        assert result.exit_code == 1
        assert "more than one profile" in result.output

    def test_unknown_token_lists_valid_values(self):
        result = runner.invoke(app, ["run", "--tools", "bogus", "-p", "hi"])
        assert result.exit_code == 1
        assert "Profiles:" in result.output
        assert "Tools:" in result.output

    def test_registry_only_tool_points_at_role_yaml(self):
        """A real tool that ephemeral mode cannot attach says why."""
        result = runner.invoke(app, ["run", "--tools", "clarify", "-p", "hi"])
        assert result.exit_code == 1
        assert "initrunner new" in result.output


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

        dispatch_ephemeral(prompt="hello", tools=["none"])
        assert mock_repl.call_args[1]["attached_tools"] == []

    @patch("initrunner.cli._ephemeral.dispatch_ephemeral_repl")
    @patch("initrunner.run_config.load_run_config")
    def test_all_includes_exec_tools(self, mock_cfg, mock_repl):
        from initrunner.run_config import RunConfig

        mock_cfg.return_value = RunConfig(provider="openai", model="gpt-5-mini")
        from initrunner.cli._ephemeral import dispatch_ephemeral

        dispatch_ephemeral(prompt="hello", tools=["all"])
        types = set(_attached_types(mock_repl.call_args[1]))
        assert {"python", "shell", "datetime", "web_reader"} <= types

    @patch("initrunner.cli._ephemeral.dispatch_ephemeral_repl")
    @patch("initrunner.run_config.load_run_config")
    def test_minimal_plus_python_extra(self, mock_cfg, mock_repl):
        from initrunner.run_config import RunConfig

        mock_cfg.return_value = RunConfig(provider="openai", model="gpt-5-mini")
        from initrunner.cli._ephemeral import dispatch_ephemeral

        dispatch_ephemeral(prompt="hello", tools=["python"])
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

    @patch("initrunner.cli._ephemeral.dispatch_ephemeral_repl")
    @patch("initrunner.run_config.load_run_config")
    def test_comma_separated_profile_and_type(self, mock_cfg, mock_repl):
        from initrunner.run_config import RunConfig

        mock_cfg.return_value = RunConfig(provider="openai", model="gpt-5-mini")
        from initrunner.cli._ephemeral import dispatch_ephemeral

        dispatch_ephemeral(prompt="hello", tools=["none,git"])
        assert _attached_types(mock_repl.call_args[1]) == ["git"]

    @patch("initrunner.cli._ephemeral.dispatch_ephemeral_repl")
    @patch("initrunner.run_config.load_run_config")
    def test_flag_types_replace_run_yaml_tools(self, mock_cfg, mock_repl):
        """An explicit --tools list replaces run.yaml's, it does not merge."""
        from initrunner.run_config import RunConfig

        mock_cfg.return_value = RunConfig(
            provider="openai", model="gpt-5-mini", tool_profile="minimal", tools=["git"]
        )
        from initrunner.cli._ephemeral import dispatch_ephemeral

        dispatch_ephemeral(prompt="hello", tools=["python"])
        assert _attached_types(mock_repl.call_args[1]) == ["datetime", "web_reader", "python"]


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
