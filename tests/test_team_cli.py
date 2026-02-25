"""Tests for team CLI integration."""

from __future__ import annotations

import textwrap
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from initrunner.cli._helpers import detect_yaml_kind
from initrunner.cli.main import app

runner = CliRunner()

_TEAM_YAML = textwrap.dedent("""\
    apiVersion: initrunner/v1
    kind: Team
    metadata:
      name: test-team
      description: A test team
    spec:
      model:
        provider: openai
        name: gpt-5-mini
      personas:
        alpha: "first persona"
        bravo: "second persona"
""")

_ROLE_YAML = textwrap.dedent("""\
    apiVersion: initrunner/v1
    kind: Agent
    metadata:
      name: test-agent
    spec:
      role: You are helpful.
      model:
        provider: openai
        name: gpt-5-mini
""")


class TestDetectYamlKind:
    def test_agent_kind(self, tmp_path):
        f = tmp_path / "role.yaml"
        f.write_text(_ROLE_YAML)
        assert detect_yaml_kind(f) == "Agent"

    def test_team_kind(self, tmp_path):
        f = tmp_path / "team.yaml"
        f.write_text(_TEAM_YAML)
        assert detect_yaml_kind(f) == "Team"

    def test_compose_kind(self, tmp_path):
        f = tmp_path / "compose.yaml"
        f.write_text("apiVersion: initrunner/v1\nkind: Compose\nmetadata:\n  name: test\n")
        assert detect_yaml_kind(f) == "Compose"

    def test_missing_kind_defaults_agent(self, tmp_path):
        f = tmp_path / "no-kind.yaml"
        f.write_text("apiVersion: initrunner/v1\nmetadata:\n  name: test\n")
        assert detect_yaml_kind(f) == "Agent"

    def test_invalid_yaml_defaults_agent(self, tmp_path):
        f = tmp_path / "bad.yaml"
        f.write_text(": invalid: yaml: [")
        assert detect_yaml_kind(f) == "Agent"

    def test_missing_file_defaults_agent(self, tmp_path):
        assert detect_yaml_kind(tmp_path / "nonexistent.yaml") == "Agent"

    def test_non_mapping_defaults_agent(self, tmp_path):
        f = tmp_path / "list.yaml"
        f.write_text("- item1\n- item2\n")
        assert detect_yaml_kind(f) == "Agent"


class TestTeamRunCli:
    @patch("initrunner.agent.loader.build_agent")
    @patch("initrunner.agent.executor.execute_run")
    @patch("initrunner.agent.loader._load_dotenv")
    def test_run_dry_run_with_task(self, mock_dotenv, mock_exec, mock_build, tmp_path):
        from initrunner.agent.executor import RunResult

        mock_build.return_value = MagicMock()
        mock_exec.return_value = (
            RunResult(run_id="r1", output="dry-run output", success=True),
            [],
        )

        team_file = tmp_path / "team.yaml"
        team_file.write_text(_TEAM_YAML)

        result = runner.invoke(
            app, ["run", str(team_file), "--task", "review this", "--dry-run", "--no-audit"]
        )
        assert result.exit_code == 0
        assert "Team mode" in result.output
        assert "test-team" in result.output

    @patch("initrunner.agent.loader.build_agent")
    @patch("initrunner.agent.executor.execute_run")
    @patch("initrunner.agent.loader._load_dotenv")
    def test_run_dry_run_with_prompt(self, mock_dotenv, mock_exec, mock_build, tmp_path):
        from initrunner.agent.executor import RunResult

        mock_build.return_value = MagicMock()
        mock_exec.return_value = (
            RunResult(run_id="r1", output="output", success=True),
            [],
        )

        team_file = tmp_path / "team.yaml"
        team_file.write_text(_TEAM_YAML)

        result = runner.invoke(
            app, ["run", str(team_file), "-p", "review this", "--dry-run", "--no-audit"]
        )
        assert result.exit_code == 0
        assert "Team mode" in result.output

    def test_run_team_without_prompt_errors(self, tmp_path):
        team_file = tmp_path / "team.yaml"
        team_file.write_text(_TEAM_YAML)

        result = runner.invoke(app, ["run", str(team_file), "--no-audit"])
        assert result.exit_code == 1
        assert "requires" in result.output

    @patch("initrunner.agent.loader.build_agent")
    @patch("initrunner.agent.executor.execute_run")
    @patch("initrunner.agent.loader._load_dotenv")
    def test_task_alias_works(self, mock_dotenv, mock_exec, mock_build, tmp_path):
        from initrunner.agent.executor import RunResult

        mock_build.return_value = MagicMock()
        mock_exec.return_value = (
            RunResult(run_id="r1", output="output", success=True),
            [],
        )

        team_file = tmp_path / "team.yaml"
        team_file.write_text(_TEAM_YAML)

        result = runner.invoke(
            app, ["run", str(team_file), "--task", "my task", "--dry-run", "--no-audit"]
        )
        assert result.exit_code == 0

    @patch("initrunner.agent.loader.build_agent")
    @patch("initrunner.agent.executor.execute_run")
    @patch("initrunner.agent.loader._load_dotenv")
    def test_persona_failure_exits_nonzero(self, mock_dotenv, mock_exec, mock_build, tmp_path):
        from initrunner.agent.executor import RunResult

        mock_build.return_value = MagicMock()
        mock_exec.side_effect = [
            (RunResult(run_id="r1", output="ok", success=True), []),
            (RunResult(run_id="r2", success=False, error="API error"), []),
        ]

        team_file = tmp_path / "team.yaml"
        team_file.write_text(_TEAM_YAML)

        result = runner.invoke(app, ["run", str(team_file), "--task", "task", "--no-audit"])
        assert result.exit_code == 1


class TestTeamValidateCli:
    def test_validate_valid_team(self, tmp_path):
        team_file = tmp_path / "team.yaml"
        team_file.write_text(_TEAM_YAML)

        result = runner.invoke(app, ["validate", str(team_file)])
        assert result.exit_code == 0
        assert "Valid" in result.output
        assert "test-team" in result.output
        assert "alpha" in result.output
        assert "bravo" in result.output

    def test_validate_invalid_team(self, tmp_path):
        bad_yaml = textwrap.dedent("""\
            apiVersion: initrunner/v1
            kind: Team
            metadata:
              name: bad-team
            spec:
              model:
                provider: openai
                name: gpt-5-mini
              personas:
                only-one: "lonely"
        """)
        team_file = tmp_path / "bad-team.yaml"
        team_file.write_text(bad_yaml)

        result = runner.invoke(app, ["validate", str(team_file)])
        assert result.exit_code == 1
        assert "Invalid" in result.output

    def test_validate_missing_team_file(self, tmp_path):
        result = runner.invoke(app, ["validate", str(tmp_path / "missing.yaml")])
        assert result.exit_code == 1

    def test_validate_displays_team_info(self, tmp_path):
        team_yaml = textwrap.dedent("""\
            apiVersion: initrunner/v1
            kind: Team
            metadata:
              name: info-team
              description: Team with details
            spec:
              model:
                provider: openai
                name: gpt-5-mini
              personas:
                reviewer: "review code"
                tester: "write tests"
              guardrails:
                max_tokens_per_run: 25000
                team_token_budget: 100000
        """)
        team_file = tmp_path / "team.yaml"
        team_file.write_text(team_yaml)

        result = runner.invoke(app, ["validate", str(team_file)])
        assert result.exit_code == 0
        assert "info-team" in result.output
        assert "Team with details" in result.output
        assert "25000" in result.output or "25,000" in result.output
        assert "100,000" in result.output or "100000" in result.output
