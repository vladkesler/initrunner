"""Tests for eval runner (load_suite + run_suite)."""

import textwrap
from unittest.mock import MagicMock

import pytest
from pydantic_ai import Agent
from pydantic_ai.models.test import TestModel

from initrunner.agent.schema.base import ApiVersion, Kind, Metadata, ModelConfig
from initrunner.agent.schema.role import AgentSpec, RoleDefinition
from initrunner.eval.runner import (
    CaseResult,
    SuiteLoadError,
    SuiteResult,
    load_suite,
    run_suite,
)
from initrunner.eval.schema import TestSuiteDefinition


def _make_role() -> RoleDefinition:
    return RoleDefinition(
        apiVersion=ApiVersion.V1,
        kind=Kind.AGENT,
        metadata=Metadata(name="test-agent"),
        spec=AgentSpec(
            role="You are a test.",
            model=ModelConfig(provider="openai", name="gpt-5-mini"),
        ),
    )


def _make_real_agent() -> Agent:
    """Create a real PydanticAI Agent for dry-run tests (model will be overridden)."""
    return Agent(TestModel())


def _make_mock_agent(output: str = "Hello!"):
    agent = MagicMock()
    result = MagicMock()
    result.output = output
    usage = MagicMock()
    usage.input_tokens = 10
    usage.output_tokens = 5
    usage.total_tokens = 15
    usage.tool_calls = 0
    result.usage.return_value = usage
    result.all_messages.return_value = []
    agent.run_sync.return_value = result
    return agent


class TestLoadSuite:
    def test_loads_valid_suite(self, tmp_path):
        suite_file = tmp_path / "suite.yaml"
        suite_file.write_text(
            textwrap.dedent("""\
            apiVersion: initrunner/v1
            kind: TestSuite
            metadata:
              name: my-suite
            cases:
              - name: basic
                prompt: "Hello"
                assertions:
                  - type: contains
                    value: hello
                    case_insensitive: true
        """)
        )
        suite = load_suite(suite_file)
        assert suite.metadata.name == "my-suite"
        assert len(suite.cases) == 1
        assert suite.cases[0].name == "basic"

    def test_missing_file(self, tmp_path):
        with pytest.raises(SuiteLoadError, match="Cannot read"):
            load_suite(tmp_path / "nonexistent.yaml")

    def test_invalid_yaml(self, tmp_path):
        suite_file = tmp_path / "bad.yaml"
        suite_file.write_text(": invalid: yaml: {{")
        with pytest.raises(SuiteLoadError, match="Invalid YAML"):
            load_suite(suite_file)

    def test_non_mapping_yaml(self, tmp_path):
        suite_file = tmp_path / "list.yaml"
        suite_file.write_text("- item1\n- item2\n")
        with pytest.raises(SuiteLoadError, match="Expected a YAML mapping"):
            load_suite(suite_file)

    def test_validation_error(self, tmp_path):
        suite_file = tmp_path / "bad.yaml"
        suite_file.write_text("apiVersion: wrong\nkind: TestSuite\n")
        with pytest.raises(SuiteLoadError, match="Validation failed"):
            load_suite(suite_file)


class TestRunSuiteDryRun:
    def test_dry_run_uses_expected_output(self):
        role = _make_role()
        agent = _make_real_agent()
        suite = TestSuiteDefinition.model_validate(
            {
                "apiVersion": "initrunner/v1",
                "kind": "TestSuite",
                "metadata": {"name": "dry-suite"},
                "cases": [
                    {
                        "name": "math",
                        "prompt": "2+2?",
                        "expected_output": "The answer is 4.",
                        "assertions": [
                            {"type": "contains", "value": "4"},
                        ],
                    },
                ],
            }
        )
        result = run_suite(agent, role, suite, dry_run=True)
        assert result.all_passed
        assert result.total == 1
        assert result.passed == 1
        assert result.case_results[0].run_result.output == "The answer is 4."

    def test_dry_run_default_output(self):
        role = _make_role()
        agent = _make_real_agent()
        suite = TestSuiteDefinition.model_validate(
            {
                "apiVersion": "initrunner/v1",
                "kind": "TestSuite",
                "metadata": {"name": "default-suite"},
                "cases": [
                    {
                        "name": "no-expected",
                        "prompt": "Hello",
                        "assertions": [],
                    },
                ],
            }
        )
        result = run_suite(agent, role, suite, dry_run=True)
        assert result.all_passed
        assert "[dry-run]" in result.case_results[0].run_result.output

    def test_dry_run_failing_assertion(self):
        role = _make_role()
        agent = _make_real_agent()
        suite = TestSuiteDefinition.model_validate(
            {
                "apiVersion": "initrunner/v1",
                "kind": "TestSuite",
                "metadata": {"name": "fail-suite"},
                "cases": [
                    {
                        "name": "should-fail",
                        "prompt": "Hello",
                        "expected_output": "Hi there!",
                        "assertions": [
                            {"type": "contains", "value": "MISSING_STRING"},
                        ],
                    },
                ],
            }
        )
        result = run_suite(agent, role, suite, dry_run=True)
        assert not result.all_passed
        assert result.failed == 1


class TestRunSuiteWithMock:
    def test_passes_with_mock_agent(self):
        role = _make_role()
        agent = _make_mock_agent(output="hello world")
        suite = TestSuiteDefinition.model_validate(
            {
                "apiVersion": "initrunner/v1",
                "kind": "TestSuite",
                "metadata": {"name": "mock-suite"},
                "cases": [
                    {
                        "name": "greeting",
                        "prompt": "Hi",
                        "assertions": [
                            {"type": "contains", "value": "hello"},
                            {"type": "not_contains", "value": "error"},
                        ],
                    },
                ],
            }
        )
        result = run_suite(agent, role, suite)
        assert result.all_passed

    def test_multiple_cases(self):
        role = _make_role()
        agent = _make_mock_agent(output="hello world 42")
        suite = TestSuiteDefinition.model_validate(
            {
                "apiVersion": "initrunner/v1",
                "kind": "TestSuite",
                "metadata": {"name": "multi-suite"},
                "cases": [
                    {
                        "name": "case1",
                        "prompt": "p1",
                        "assertions": [{"type": "contains", "value": "hello"}],
                    },
                    {
                        "name": "case2",
                        "prompt": "p2",
                        "assertions": [{"type": "regex", "pattern": r"\d+"}],
                    },
                ],
            }
        )
        result = run_suite(agent, role, suite)
        assert result.total == 2
        assert result.all_passed


class TestSuiteResultProperties:
    def test_properties(self):
        sr = SuiteResult(suite_name="test")
        assert sr.total == 0
        assert sr.passed == 0
        assert sr.failed == 0
        assert sr.all_passed is True  # vacuously true

    def test_with_results(self):
        from initrunner.agent.executor import RunResult
        from initrunner.eval.schema import TestCase

        sr = SuiteResult(
            suite_name="test",
            case_results=[
                CaseResult(
                    case=TestCase(name="a", prompt="p"),
                    run_result=RunResult(run_id="1"),
                    assertion_results=[],
                    passed=True,
                ),
                CaseResult(
                    case=TestCase(name="b", prompt="p"),
                    run_result=RunResult(run_id="2"),
                    assertion_results=[],
                    passed=False,
                ),
            ],
        )
        assert sr.total == 2
        assert sr.passed == 1
        assert sr.failed == 1
        assert sr.all_passed is False
