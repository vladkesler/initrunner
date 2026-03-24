"""Tests for unified run command dispatch and flag validation."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from initrunner.cli.main import app

runner = CliRunner()


@pytest.fixture
def agent_yaml(tmp_path: Path) -> Path:
    p = tmp_path / "role.yaml"
    p.write_text(
        "apiVersion: initrunner/v1\nkind: Agent\nmetadata:\n  name: t\n"
        "spec:\n  role: test\n  model:\n    provider: openai\n    name: gpt-5-mini\n"
    )
    return p


@pytest.fixture
def compose_yaml(tmp_path: Path) -> Path:
    p = tmp_path / "compose.yaml"
    p.write_text(
        "apiVersion: initrunner/v1\nkind: Compose\nmetadata:\n  name: t\nspec:\n  services: {}\n"
    )
    return p


@pytest.fixture
def pipeline_yaml(tmp_path: Path) -> Path:
    p = tmp_path / "pipeline.yaml"
    p.write_text(
        "apiVersion: initrunner/v1\nkind: Pipeline\nmetadata:\n  name: t\nspec:\n  steps: []\n"
    )
    return p


@pytest.fixture
def team_yaml(tmp_path: Path) -> Path:
    p = tmp_path / "team.yaml"
    p.write_text(
        "apiVersion: initrunner/v1\nkind: Team\nmetadata:\n  name: t\nspec:\n  personas: {}\n"
    )
    return p


class TestMutualExclusivity:
    def test_daemon_and_serve_exclusive(self, agent_yaml):
        result = runner.invoke(app, ["run", str(agent_yaml), "--daemon", "--serve"])
        assert result.exit_code == 1
        assert "mutually exclusive" in result.output

    def test_daemon_and_autonomous_exclusive(self, agent_yaml):
        result = runner.invoke(app, ["run", str(agent_yaml), "--daemon", "-a", "-p", "hi"])
        assert result.exit_code == 1
        assert "mutually exclusive" in result.output

    def test_serve_and_bot_exclusive(self, agent_yaml):
        result = runner.invoke(app, ["run", str(agent_yaml), "--serve", "--bot", "telegram"])
        assert result.exit_code == 1
        assert "mutually exclusive" in result.output

    def test_bot_and_autonomous_exclusive(self, agent_yaml):
        result = runner.invoke(app, ["run", str(agent_yaml), "--bot", "telegram", "-a", "-p", "hi"])
        assert result.exit_code == 1
        assert "mutually exclusive" in result.output


class TestBotValidation:
    def test_bot_invalid_platform(self, agent_yaml):
        result = runner.invoke(app, ["run", str(agent_yaml), "--bot", "whatsapp"])
        assert result.exit_code == 1
        assert "telegram" in result.output and "discord" in result.output


class TestKindFlagValidation:
    def test_compose_rejects_prompt(self, compose_yaml):
        result = runner.invoke(app, ["run", str(compose_yaml), "-p", "hello"])
        assert result.exit_code == 1
        assert "--prompt" in result.output
        assert "Compose" in result.output

    def test_compose_rejects_daemon(self, compose_yaml):
        result = runner.invoke(app, ["run", str(compose_yaml), "--daemon"])
        assert result.exit_code == 1
        assert "--daemon" in result.output

    def test_compose_rejects_serve(self, compose_yaml):
        result = runner.invoke(app, ["run", str(compose_yaml), "--serve"])
        assert result.exit_code == 1
        assert "--serve" in result.output

    def test_pipeline_rejects_interactive(self, pipeline_yaml):
        result = runner.invoke(app, ["run", str(pipeline_yaml), "-i"])
        assert result.exit_code == 1
        assert "--interactive" in result.output

    def test_pipeline_rejects_bot(self, pipeline_yaml):
        result = runner.invoke(app, ["run", str(pipeline_yaml), "--bot", "telegram"])
        assert result.exit_code == 1
        assert "--bot" in result.output

    def test_var_only_for_pipeline(self, agent_yaml):
        result = runner.invoke(app, ["run", str(agent_yaml), "--var", "x=1"])
        assert result.exit_code == 1
        assert "--var" in result.output
        assert "Pipeline" in result.output

    def test_daemon_only_for_agent(self, team_yaml):
        result = runner.invoke(app, ["run", str(team_yaml), "--daemon"])
        assert result.exit_code == 1
        assert "Agent" in result.output


class TestComposeDispatch:
    def test_compose_yaml_dispatches(self, compose_yaml):
        with patch("initrunner.cli.run_cmd._dispatch_compose") as mock_dispatch:
            result = runner.invoke(app, ["run", str(compose_yaml)])

        assert result.exit_code == 0
        mock_dispatch.assert_called_once()

    def test_pipeline_yaml_dispatches(self, pipeline_yaml):
        with patch("initrunner.cli.run_cmd._dispatch_pipeline") as mock_dispatch:
            result = runner.invoke(app, ["run", str(pipeline_yaml)])

        assert result.exit_code == 0
        mock_dispatch.assert_called_once()


class TestDaemonFlag:
    def test_daemon_flag_dispatches(self, agent_yaml):
        with patch("initrunner.cli.run_cmd._dispatch_daemon") as mock_dispatch:
            result = runner.invoke(app, ["run", str(agent_yaml), "--daemon"])

        assert result.exit_code == 0
        mock_dispatch.assert_called_once()


class TestServeFlag:
    def test_serve_flag_dispatches(self, agent_yaml):
        with patch("initrunner.cli.run_cmd._dispatch_serve") as mock_dispatch:
            result = runner.invoke(app, ["run", str(agent_yaml), "--serve"])

        assert result.exit_code == 0
        mock_dispatch.assert_called_once()


class TestBotFlag:
    def test_bot_flag_dispatches(self, agent_yaml):
        with patch("initrunner.cli.run_cmd._dispatch_bot") as mock_dispatch:
            result = runner.invoke(app, ["run", str(agent_yaml), "--bot", "telegram"])

        assert result.exit_code == 0
        mock_dispatch.assert_called_once()
        args = mock_dispatch.call_args
        assert args[0][1] == "telegram"


class TestTriggerHint:
    def test_trigger_hint_shown(self, agent_yaml, monkeypatch):
        """When role has triggers and entering REPL, show --daemon hint."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

        mock_role = MagicMock()
        mock_role.spec.triggers = [MagicMock()]
        mock_role.spec.memory = None
        mock_role.spec.observability = None
        mock_role.spec.sinks = []
        mock_role.spec.output.type = "text"

        from contextlib import contextmanager

        @contextmanager
        def _ctx(*a, **kw):
            yield mock_role, MagicMock(), None, None, None

        with (
            patch("initrunner.cli.run_cmd.resolve_run_target", return_value=(agent_yaml, "Agent")),
            patch("initrunner.cli._run_agent.command_context", _ctx),
            patch("initrunner.runner.run_interactive"),
        ):
            result = runner.invoke(app, ["run", str(agent_yaml)])

        assert "--daemon" in result.output


class TestOldCommandsRemoved:
    def test_daemon_command_gone(self):
        result = runner.invoke(app, ["daemon", "some-role.yaml"])
        assert result.exit_code == 2  # typer "no such command"

    def test_serve_command_gone(self):
        result = runner.invoke(app, ["serve", "some-role.yaml"])
        assert result.exit_code == 2

    def test_pipeline_command_gone(self):
        result = runner.invoke(app, ["pipeline", "some-pipeline.yaml"])
        assert result.exit_code == 2
