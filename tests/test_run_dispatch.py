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
        "apiVersion: initrunner/v1\nkind: Agent\nmetadata:\n  name: test-agent\n"
        "spec:\n  role: You are a helpful assistant.\n"
        "  model:\n    provider: openai\n    name: gpt-5-mini\n"
    )
    return p


@pytest.fixture
def flow_yaml(tmp_path: Path) -> Path:
    # Pre-flight recurses into referenced role files, so write a real role too.
    role = tmp_path / "worker.yaml"
    role.write_text(
        "apiVersion: initrunner/v1\nkind: Agent\nmetadata:\n  name: worker\n"
        "spec:\n  role: You are a worker.\n"
        "  model:\n    provider: openai\n    name: gpt-5-mini\n"
    )
    p = tmp_path / "flow.yaml"
    p.write_text(
        "apiVersion: initrunner/v1\nkind: Flow\nmetadata:\n  name: test-flow\n"
        "spec:\n  agents:\n    worker:\n      role: worker.yaml\n"
    )
    return p


@pytest.fixture
def team_yaml(tmp_path: Path) -> Path:
    p = tmp_path / "team.yaml"
    p.write_text(
        "apiVersion: initrunner/v1\nkind: Team\nmetadata:\n  name: test-team\n"
        "spec:\n  model:\n    provider: openai\n    name: gpt-5-mini\n"
        '  personas:\n    alpha: "first persona"\n    bravo: "second persona"\n'
    )
    return p


class TestMutualExclusivity:
    def test_daemon_and_serve_exclusive(self, agent_yaml):
        result = runner.invoke(app, ["run", str(agent_yaml), "--daemon", "--serve"])
        assert result.exit_code == 1
        assert "Cannot combine" in result.output
        assert "--daemon" in result.output and "--serve" in result.output

    def test_daemon_and_autonomous_exclusive(self, agent_yaml):
        result = runner.invoke(app, ["run", str(agent_yaml), "--daemon", "-a", "-p", "hi"])
        assert result.exit_code == 1
        assert "Cannot combine" in result.output
        assert "--daemon" in result.output and "--autonomous" in result.output

    def test_serve_and_autonomous_exclusive(self, agent_yaml):
        result = runner.invoke(app, ["run", str(agent_yaml), "--serve", "-a", "-p", "hi"])
        assert result.exit_code == 1
        assert "Cannot combine" in result.output
        assert "--serve" in result.output and "--autonomous" in result.output


class TestKindFlagValidation:
    def test_flow_accepts_prompt_as_one_shot(self, flow_yaml):
        result = runner.invoke(app, ["run", str(flow_yaml), "-p", "hello"])
        assert "--prompt" not in result.output or "not supported" not in result.output

    def test_flow_rejects_daemon(self, flow_yaml):
        result = runner.invoke(app, ["run", str(flow_yaml), "--daemon"])
        assert result.exit_code == 1
        assert "--daemon" in result.output

    def test_flow_rejects_serve(self, flow_yaml):
        result = runner.invoke(app, ["run", str(flow_yaml), "--serve"])
        assert result.exit_code == 1
        assert "--serve" in result.output

    def test_daemon_only_for_agent(self, team_yaml):
        result = runner.invoke(app, ["run", str(team_yaml), "--daemon"])
        assert result.exit_code == 1
        assert "Agent" in result.output


class TestFlowDispatch:
    def test_flow_yaml_dispatches(self, flow_yaml):
        with patch("initrunner.cli.run_cmd._command._dispatch_flow") as mock_dispatch:
            result = runner.invoke(app, ["run", str(flow_yaml)])

        assert result.exit_code == 0
        mock_dispatch.assert_called_once()


class TestPipelineKindRejected:
    def test_pipeline_kind_rejected_run(self, tmp_path):
        p = tmp_path / "pipeline.yaml"
        p.write_text(
            "apiVersion: initrunner/v1\nkind: Pipeline\nmetadata:\n  name: t\nspec:\n  steps: []\n"
        )
        result = runner.invoke(app, ["run", str(p)])
        assert result.exit_code == 1
        assert "Pipeline has been removed" in result.output
        assert "Team" in result.output

    def test_pipeline_kind_rejected_validate(self, tmp_path):
        p = tmp_path / "pipeline.yaml"
        p.write_text(
            "apiVersion: initrunner/v1\nkind: Pipeline\nmetadata:\n  name: t\nspec:\n  steps: []\n"
        )
        result = runner.invoke(app, ["validate", str(p)])
        assert result.exit_code == 1
        assert "Pipeline has been removed" in result.output
        assert "Team" in result.output


class TestDaemonFlag:
    def test_daemon_flag_dispatches(self, agent_yaml):
        with patch("initrunner.cli.run_cmd._command._dispatch_daemon") as mock_dispatch:
            result = runner.invoke(app, ["run", str(agent_yaml), "--daemon"])

        assert result.exit_code == 0
        mock_dispatch.assert_called_once()


class TestServeFlag:
    def test_serve_flag_dispatches(self, agent_yaml):
        with patch("initrunner.cli.run_cmd._command._dispatch_serve") as mock_dispatch:
            result = runner.invoke(app, ["run", str(agent_yaml), "--serve"])

        assert result.exit_code == 0
        mock_dispatch.assert_called_once()


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
            patch(
                "initrunner.cli.run_cmd._command.resolve_run_target",
                return_value=(agent_yaml, "Agent"),
            ),
            patch("initrunner.cli._run_agent.command_context", _ctx),
            patch("initrunner.runner.run_interactive"),
        ):
            result = runner.invoke(app, ["run", str(agent_yaml)])

        assert "--daemon" in result.output


class TestInlineApiKeyPrompt:
    def test_inline_prompt_recovers_through_run_command(self, agent_yaml, tmp_path, monkeypatch):
        """End-to-end retry path: missing API key triggers the inline
        prompt helper, the key is set in env, and ``command_context()``
        yields cleanly on the second build attempt.

        This guards against regressions where a future change to
        ``command_context()`` accidentally breaks when ``load_and_build``
        succeeds on its second call rather than its first.

        The TTY gate inside ``prompt_inline_api_key`` is exhaustively
        covered by ``tests/test_cli_inline_setup.py``.  CliRunner replaces
        ``sys.stdin`` during ``invoke``, so monkey-patching ``isatty``
        before the call doesn't apply to the swapped object.  We sidestep
        that by stubbing the helper directly -- the integration test's
        purpose is the retry path through ``command_context()``, not the
        TTY check.
        """
        import os as _os

        for var in (
            "OPENAI_API_KEY",
            "ANTHROPIC_API_KEY",
            "GOOGLE_API_KEY",
            "GROQ_API_KEY",
            "MISTRAL_API_KEY",
            "CO_API_KEY",
            "XAI_API_KEY",
        ):
            monkeypatch.delenv(var, raising=False)
        monkeypatch.setenv("INITRUNNER_HOME", str(tmp_path / "home"))

        from initrunner.config import get_home_dir

        get_home_dir.cache_clear()

        def stub_prompt(env_var, provider):
            from initrunner.services.setup import save_env_key

            _os.environ[env_var] = "sk-test-inline"
            save_env_key(env_var, "sk-test-inline")
            return True

        mock_run = MagicMock(return_value=(MagicMock(), None))
        with (
            patch(
                "initrunner.cli._helpers._context.prompt_inline_api_key",
                side_effect=stub_prompt,
            ) as prompt_spy,
            patch("initrunner.runner.run_single", mock_run),
            patch("initrunner.runner.run_single_stream", mock_run),
            patch("initrunner.cli._run_agent._run_formatted", mock_run),
        ):
            result = runner.invoke(
                app,
                ["run", str(agent_yaml), "-p", "hello", "--no-audit"],
            )

        get_home_dir.cache_clear()

        assert result.exit_code == 0, f"output={result.output}\nexception={result.exception}"
        prompt_spy.assert_called_once()
        env_var, provider = prompt_spy.call_args[0]
        assert env_var == "OPENAI_API_KEY"
        assert provider == "openai"

        # command_context() must have yielded -- the runner mock would
        # never be called otherwise.
        assert mock_run.called

        env_file = tmp_path / "home" / ".env"
        assert env_file.is_file()
        assert "sk-test-inline" in env_file.read_text()


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


class TestRemovedFlags:
    """Removed flags name their replacement instead of "No such option".

    Delete alongside `initrunner/cli/run_cmd/_removed.py` one release on.
    """

    @pytest.mark.parametrize(
        ("argv", "expected"),
        [
            (["--max-iterations", "5"], "guardrails.max_iterations"),
            (["--token-budget", "100"], "guardrails.run_token_budget"),
            (["--budget-timezone", "UTC"], "guardrails.budget_timezone"),
            (["--allowed-users", "alice"], "allowed_users"),
            (["--allowed-user-ids", "1"], "allowed_user_ids"),
            (["--cors-origin", "https://x"], "security.server.cors_origins"),
            (["--api-key", "k"], "INITRUNNER_API_KEY"),
            (["--autopilot"], "autonomy: {}"),
            (["--provider", "openai"], "--model provider:model"),
            (["--tool-profile", "all"], "--tools none|minimal|all"),
            (["--list-tools"], "--tools"),
            (["--explain-profiles"], "--tools"),
            (["--role-dir", "."], "--sense already searches"),
            (["--confirm-role"], "--sense already confirms"),
            (["--report-template", "pr-review"], "--report TEMPLATE:PATH"),
            (["--save", "out"], "examples copy"),
            (["--no-stream"], "--format rich"),
            (["--dev"], "--format rich"),
            (["--audit-db", "a.db"], "INITRUNNER_AUDIT_DB"),
            (["--skill-dir", "s"], "INITRUNNER_SKILL_DIR"),
            (["--bot", "telegram"], "--daemon"),
        ],
    )
    def test_removed_flag_names_its_replacement(self, agent_yaml, argv, expected):
        result = runner.invoke(app, ["run", str(agent_yaml), *argv])
        assert result.exit_code == 2
        assert "was removed" in result.output
        assert expected in result.output

    def test_equals_form_is_recognised(self, agent_yaml):
        """Click splits --flag=value before matching, so both forms hit."""
        result = runner.invoke(app, ["run", str(agent_yaml), "--max-iterations=5"])
        assert result.exit_code == 2
        assert "guardrails.max_iterations" in result.output

    def test_removed_flag_without_a_role_file(self):
        result = runner.invoke(app, ["run", "--tool-profile", "all"])
        assert result.exit_code == 2
        assert "--tools" in result.output

    def test_unrelated_unknown_flag_keeps_click_message(self, agent_yaml):
        result = runner.invoke(app, ["run", str(agent_yaml), "--not-a-real-flag"])
        assert result.exit_code == 2
        assert "was removed" not in result.output
        assert "No such option" in result.output

    def test_help_is_unaffected(self):
        result = runner.invoke(app, ["run", "--help"])
        assert result.exit_code == 0
        assert "was removed" not in result.output
        for gone in ("--autopilot", "--bot", "--tool-profile", "--save", "--dev"):
            assert gone not in result.output
