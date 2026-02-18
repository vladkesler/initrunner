"""Tests for --dry-run flag on run and test CLI commands."""

import textwrap
from unittest.mock import MagicMock, patch

from pydantic_ai import Agent
from pydantic_ai.models.test import TestModel
from typer.testing import CliRunner

from initrunner.cli.main import app

runner = CliRunner()

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

_SUITE_YAML = textwrap.dedent("""\
    apiVersion: initrunner/v1
    kind: TestSuite
    metadata:
      name: basic-tests
    cases:
      - name: greeting
        prompt: "Hello!"
        expected_output: "Hi there! How can I help?"
        assertions:
          - type: contains
            value: "Hi"
          - type: not_contains
            value: "error"
      - name: simulated
        prompt: "Test"
        assertions: []
""")

_SUITE_FAILING_YAML = textwrap.dedent("""\
    apiVersion: initrunner/v1
    kind: TestSuite
    metadata:
      name: failing-tests
    cases:
      - name: will-fail
        prompt: "Hello"
        expected_output: "Some output"
        assertions:
          - type: contains
            value: "DEFINITELY_NOT_PRESENT"
""")


class TestRunDryRun:
    @patch("initrunner.runner.run_single")
    @patch("initrunner.agent.loader.load_and_build")
    def test_dry_run_passes_model_override(self, mock_load, mock_run_single, tmp_path):
        from initrunner.agent.executor import RunResult

        role = MagicMock()
        role.spec.memory = None
        role.spec.sinks = []
        role.spec.observability = None
        agent = MagicMock()
        mock_load.return_value = (role, agent)
        mock_run_single.return_value = (
            RunResult(run_id="test", output="[dry-run] Simulated response.", success=True),
            [],
        )

        role_file = tmp_path / "role.yaml"
        role_file.write_text(_ROLE_YAML)

        result = runner.invoke(
            app, ["run", str(role_file), "-p", "hello", "--dry-run", "--no-audit"]
        )
        assert result.exit_code == 0
        mock_run_single.assert_called_once()
        call_kwargs = mock_run_single.call_args
        model_override = call_kwargs.kwargs.get("model_override")
        assert model_override is not None

    @patch("initrunner.runner.run_single")
    @patch("initrunner.agent.loader.load_and_build")
    def test_no_dry_run_no_model_override(self, mock_load, mock_run_single, tmp_path):
        from initrunner.agent.executor import RunResult

        role = MagicMock()
        role.spec.memory = None
        role.spec.sinks = []
        role.spec.observability = None
        agent = MagicMock()
        mock_load.return_value = (role, agent)
        mock_run_single.return_value = (
            RunResult(run_id="test", output="hello", success=True),
            [],
        )

        role_file = tmp_path / "role.yaml"
        role_file.write_text(_ROLE_YAML)

        result = runner.invoke(app, ["run", str(role_file), "-p", "hello", "--no-audit"])
        assert result.exit_code == 0
        call_kwargs = mock_run_single.call_args
        model_override = call_kwargs.kwargs.get("model_override")
        assert model_override is None


def _make_mock_role():
    from initrunner.agent.schema.security import SecurityPolicy

    role = MagicMock()
    role.metadata.name = "test-agent"
    role.spec.guardrails.max_tokens_per_run = 50000
    role.spec.guardrails.max_request_limit = 50
    role.spec.guardrails.max_tool_calls = 20
    role.spec.guardrails.timeout_seconds = 300
    role.spec.guardrails.input_tokens_limit = None
    role.spec.guardrails.total_tokens_limit = None
    role.spec.security = SecurityPolicy()
    return role


class TestTestCommand:
    @patch("initrunner.agent.loader.load_and_build")
    def test_dry_run_all_pass(self, mock_load, tmp_path):
        role = _make_mock_role()
        agent = Agent(TestModel())
        mock_load.return_value = (role, agent)

        role_file = tmp_path / "role.yaml"
        role_file.write_text(_ROLE_YAML)
        suite_file = tmp_path / "suite.yaml"
        suite_file.write_text(_SUITE_YAML)

        result = runner.invoke(
            app, ["test", str(role_file), "--suite", str(suite_file), "--dry-run"]
        )
        assert result.exit_code == 0
        assert "PASS" in result.output
        assert "2/2 passed" in result.output

    @patch("initrunner.agent.loader.load_and_build")
    def test_dry_run_with_failure(self, mock_load, tmp_path):
        role = _make_mock_role()
        agent = Agent(TestModel())
        mock_load.return_value = (role, agent)

        role_file = tmp_path / "role.yaml"
        role_file.write_text(_ROLE_YAML)
        suite_file = tmp_path / "suite.yaml"
        suite_file.write_text(_SUITE_FAILING_YAML)

        result = runner.invoke(
            app, ["test", str(role_file), "--suite", str(suite_file), "--dry-run"]
        )
        assert result.exit_code == 1
        assert "FAIL" in result.output

    @patch("initrunner.agent.loader.load_and_build")
    def test_verbose_flag(self, mock_load, tmp_path):
        role = _make_mock_role()
        agent = Agent(TestModel())
        mock_load.return_value = (role, agent)

        role_file = tmp_path / "role.yaml"
        role_file.write_text(_ROLE_YAML)
        suite_file = tmp_path / "suite.yaml"
        suite_file.write_text(_SUITE_YAML)

        result = runner.invoke(
            app,
            ["test", str(role_file), "--suite", str(suite_file), "--dry-run", "--verbose"],
        )
        assert result.exit_code == 0
        # Verbose should show assertion details
        assert "contains" in result.output.lower() or "Hi" in result.output

    @patch("initrunner.agent.loader.load_and_build")
    def test_missing_suite_file(self, mock_load, tmp_path):
        role = _make_mock_role()
        agent = Agent(TestModel())
        mock_load.return_value = (role, agent)

        role_file = tmp_path / "role.yaml"
        role_file.write_text(_ROLE_YAML)

        result = runner.invoke(
            app, ["test", str(role_file), "--suite", str(tmp_path / "missing.yaml")]
        )
        assert result.exit_code == 1
        assert "Error" in result.output

    @patch("initrunner.agent.loader.load_and_build")
    def test_invalid_suite_yaml(self, mock_load, tmp_path):
        role = _make_mock_role()
        agent = Agent(TestModel())
        mock_load.return_value = (role, agent)

        role_file = tmp_path / "role.yaml"
        role_file.write_text(_ROLE_YAML)
        suite_file = tmp_path / "bad_suite.yaml"
        suite_file.write_text("apiVersion: wrong\nkind: TestSuite\n")

        result = runner.invoke(app, ["test", str(role_file), "--suite", str(suite_file)])
        assert result.exit_code == 1

    def test_missing_role_file(self, tmp_path):
        suite_file = tmp_path / "suite.yaml"
        suite_file.write_text(_SUITE_YAML)

        result = runner.invoke(app, ["test", "/nonexistent/role.yaml", "--suite", str(suite_file)])
        assert result.exit_code == 1
