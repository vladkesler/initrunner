"""Tests for eval runner (load_suite + run_suite)."""

import json
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
    _run_single_case,
    load_suite,
    run_suite,
)
from initrunner.eval.schema import TestCase, TestSuiteDefinition


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
                    run_result=RunResult(run_id="1", total_tokens=100, tokens_in=80, tokens_out=20),
                    assertion_results=[],
                    passed=True,
                    duration_ms=500,
                ),
                CaseResult(
                    case=TestCase(name="b", prompt="p"),
                    run_result=RunResult(
                        run_id="2", total_tokens=200, tokens_in=150, tokens_out=50
                    ),
                    assertion_results=[],
                    passed=False,
                    duration_ms=300,
                ),
            ],
        )
        assert sr.total == 2
        assert sr.passed == 1
        assert sr.failed == 1
        assert sr.all_passed is False

    def test_aggregate_tokens(self):
        from initrunner.agent.executor import RunResult

        sr = SuiteResult(
            suite_name="test",
            case_results=[
                CaseResult(
                    case=TestCase(name="a", prompt="p"),
                    run_result=RunResult(run_id="1", total_tokens=100),
                    assertion_results=[],
                    passed=True,
                    duration_ms=500,
                ),
                CaseResult(
                    case=TestCase(name="b", prompt="p"),
                    run_result=RunResult(run_id="2", total_tokens=200),
                    assertion_results=[],
                    passed=True,
                    duration_ms=300,
                ),
            ],
        )
        assert sr.total_tokens == 300
        assert sr.total_duration_ms == 800
        assert sr.avg_duration_ms == 400

    def test_avg_duration_empty(self):
        sr = SuiteResult(suite_name="empty")
        assert sr.avg_duration_ms == 0


class TestToDict:
    def test_schema_stability(self):
        from initrunner.agent.executor import RunResult
        from initrunner.eval.assertions import AssertionResult
        from initrunner.eval.schema import ContainsAssertion

        a = ContainsAssertion(value="hello")
        sr = SuiteResult(
            suite_name="test-suite",
            case_results=[
                CaseResult(
                    case=TestCase(name="case-1", prompt="p"),
                    run_result=RunResult(
                        run_id="r1",
                        output="hello world output that is long",
                        tokens_in=80,
                        tokens_out=20,
                        total_tokens=100,
                        tool_call_names=["search"],
                    ),
                    assertion_results=[
                        AssertionResult(
                            assertion=a, passed=True, message="Output contains 'hello'"
                        ),
                    ],
                    passed=True,
                    duration_ms=500,
                ),
            ],
        )
        d = sr.to_dict()
        assert d["suite_name"] == "test-suite"
        assert "timestamp" in d
        assert d["summary"]["total"] == 1
        assert d["summary"]["passed"] == 1
        assert d["summary"]["failed"] == 0
        assert d["summary"]["total_tokens"] == 100
        assert d["summary"]["total_duration_ms"] == 500
        assert len(d["cases"]) == 1

        case = d["cases"][0]
        assert case["name"] == "case-1"
        assert case["passed"] is True
        assert case["duration_ms"] == 500
        assert case["tokens"]["input"] == 80
        assert case["tokens"]["output"] == 20
        assert case["tokens"]["total"] == 100
        assert case["tool_calls"] == ["search"]
        assert len(case["assertions"]) == 1
        assert case["assertions"][0]["type"] == "contains"
        assert case["assertions"][0]["passed"] is True
        assert case["error"] is None
        assert case["output_preview"] == "hello world output that is long"

    def test_output_preview_truncation(self):
        from initrunner.agent.executor import RunResult

        sr = SuiteResult(
            suite_name="test",
            case_results=[
                CaseResult(
                    case=TestCase(name="long", prompt="p"),
                    run_result=RunResult(run_id="r1", output="x" * 500),
                    assertion_results=[],
                    passed=True,
                    duration_ms=100,
                ),
            ],
        )
        d = sr.to_dict()
        assert len(d["cases"][0]["output_preview"]) == 200

    def test_json_serializable(self):
        from initrunner.agent.executor import RunResult

        sr = SuiteResult(
            suite_name="test",
            case_results=[
                CaseResult(
                    case=TestCase(name="a", prompt="p"),
                    run_result=RunResult(run_id="r1", output="out", error="oops"),
                    assertion_results=[],
                    passed=False,
                    duration_ms=100,
                ),
            ],
        )
        serialized = json.dumps(sr.to_dict())
        assert isinstance(serialized, str)
        parsed = json.loads(serialized)
        assert parsed["cases"][0]["error"] == "oops"


class TestTagFiltering:
    def test_filter_by_tag(self):
        role = _make_role()
        agent = _make_real_agent()
        suite = TestSuiteDefinition.model_validate(
            {
                "apiVersion": "initrunner/v1",
                "kind": "TestSuite",
                "metadata": {"name": "tag-suite"},
                "cases": [
                    {"name": "tagged", "prompt": "p1", "tags": ["search"]},
                    {"name": "untagged", "prompt": "p2"},
                    {"name": "other", "prompt": "p3", "tags": ["fast"]},
                ],
            }
        )
        result = run_suite(agent, role, suite, dry_run=True, tag_filter=["search"])
        assert result.total == 1
        assert result.case_results[0].case.name == "tagged"

    def test_filter_by_multiple_tags(self):
        role = _make_role()
        agent = _make_real_agent()
        suite = TestSuiteDefinition.model_validate(
            {
                "apiVersion": "initrunner/v1",
                "kind": "TestSuite",
                "metadata": {"name": "tag-suite"},
                "cases": [
                    {"name": "a", "prompt": "p1", "tags": ["search"]},
                    {"name": "b", "prompt": "p2", "tags": ["fast"]},
                    {"name": "c", "prompt": "p3"},
                ],
            }
        )
        result = run_suite(agent, role, suite, dry_run=True, tag_filter=["search", "fast"])
        assert result.total == 2

    def test_no_filter_runs_all(self):
        role = _make_role()
        agent = _make_real_agent()
        suite = TestSuiteDefinition.model_validate(
            {
                "apiVersion": "initrunner/v1",
                "kind": "TestSuite",
                "metadata": {"name": "no-filter"},
                "cases": [
                    {"name": "a", "prompt": "p1", "tags": ["x"]},
                    {"name": "b", "prompt": "p2"},
                ],
            }
        )
        result = run_suite(agent, role, suite, dry_run=True)
        assert result.total == 2

    def test_filter_no_match_returns_empty(self):
        role = _make_role()
        agent = _make_real_agent()
        suite = TestSuiteDefinition.model_validate(
            {
                "apiVersion": "initrunner/v1",
                "kind": "TestSuite",
                "metadata": {"name": "empty-filter"},
                "cases": [
                    {"name": "a", "prompt": "p1", "tags": ["search"]},
                ],
            }
        )
        result = run_suite(agent, role, suite, dry_run=True, tag_filter=["nonexistent"])
        assert result.total == 0


class TestConcurrentExecution:
    def test_concurrent_preserves_order(self):
        """Verify result order is deterministic regardless of completion order."""
        role = _make_role()

        def factory():
            return _make_real_agent(), role

        suite = TestSuiteDefinition.model_validate(
            {
                "apiVersion": "initrunner/v1",
                "kind": "TestSuite",
                "metadata": {"name": "concurrent-suite"},
                "cases": [{"name": f"case-{i}", "prompt": f"prompt-{i}"} for i in range(5)],
            }
        )
        result = run_suite(suite=suite, dry_run=True, concurrency=3, agent_factory=factory)
        assert result.total == 5
        names = [cr.case.name for cr in result.case_results]
        assert names == [f"case-{i}" for i in range(5)]

    def test_concurrent_single_case(self):
        role = _make_role()

        def factory():
            return _make_real_agent(), role

        suite = TestSuiteDefinition.model_validate(
            {
                "apiVersion": "initrunner/v1",
                "kind": "TestSuite",
                "metadata": {"name": "single"},
                "cases": [{"name": "only", "prompt": "p"}],
            }
        )
        result = run_suite(suite=suite, dry_run=True, concurrency=2, agent_factory=factory)
        assert result.total == 1


class TestRunSingleCase:
    def test_basic(self):
        role = _make_role()
        agent = _make_real_agent()
        case = TestCase(name="basic", prompt="hello", expected_output="dry run output")
        cr = _run_single_case(agent, role, case, dry_run=True)
        assert cr.passed is True
        assert cr.duration_ms >= 0
        assert cr.run_result.output == "dry run output"

    def test_with_assertions(self):
        role = _make_role()
        agent = _make_real_agent()
        case = TestCase.model_validate(
            {
                "name": "asserted",
                "prompt": "hello",
                "expected_output": "The answer is 4.",
                "assertions": [{"type": "contains", "value": "4"}],
            }
        )
        cr = _run_single_case(agent, role, case, dry_run=True)
        assert cr.passed is True
        assert len(cr.assertion_results) == 1
        assert cr.assertion_results[0].passed is True
