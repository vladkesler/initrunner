"""Tests for eval services layer."""

import json
from unittest.mock import MagicMock, patch

import pytest
from pydantic_ai import Agent
from pydantic_ai.models.test import TestModel

from initrunner.agent.schema.base import ApiVersion, Kind, Metadata, ModelConfig
from initrunner.agent.schema.role import AgentSpec, RoleDefinition
from initrunner.eval.schema import TestSuiteDefinition
from initrunner.services.eval import run_suite_sync, save_result


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


def _make_suite() -> TestSuiteDefinition:
    return TestSuiteDefinition.model_validate(
        {
            "apiVersion": "initrunner/v1",
            "kind": "TestSuite",
            "metadata": {"name": "svc-suite"},
            "cases": [
                {"name": "c1", "prompt": "hello", "expected_output": "world"},
                {"name": "c2", "prompt": "test", "expected_output": "done"},
            ],
        }
    )


class TestRunSuiteSync:
    def test_single_concurrency(self):
        role = _make_role()
        agent = Agent(TestModel())
        suite = _make_suite()
        result = run_suite_sync(agent, role, suite, dry_run=True)
        assert result.total == 2
        assert result.all_passed

    def test_concurrent_requires_role_file(self):
        """When concurrency > 1 but no role_file, falls back to sequential."""
        role = _make_role()
        agent = Agent(TestModel())
        suite = _make_suite()
        result = run_suite_sync(agent, role, suite, dry_run=True, concurrency=2)
        assert result.total == 2

    @patch("initrunner.eval.runner.run_suite")
    def test_concurrent_uses_factory(self, mock_run_suite):
        from initrunner.eval.runner import SuiteResult

        mock_run_suite.return_value = SuiteResult(suite_name="test")
        role = _make_role()
        agent = Agent(TestModel())
        suite = _make_suite()

        run_suite_sync(agent, role, suite, dry_run=True, concurrency=2, role_file="/fake/role.yaml")
        mock_run_suite.assert_called_once()
        call_kwargs = mock_run_suite.call_args
        assert call_kwargs.kwargs.get("concurrency") == 2
        assert call_kwargs.kwargs.get("agent_factory") is not None

    def test_tag_filter_passed_through(self):
        role = _make_role()
        agent = Agent(TestModel())
        suite = TestSuiteDefinition.model_validate(
            {
                "apiVersion": "initrunner/v1",
                "kind": "TestSuite",
                "metadata": {"name": "tagged"},
                "cases": [
                    {"name": "a", "prompt": "p", "tags": ["x"]},
                    {"name": "b", "prompt": "p"},
                ],
            }
        )
        result = run_suite_sync(agent, role, suite, dry_run=True, tag_filter=["x"])
        assert result.total == 1


class TestSaveResult:
    def test_writes_json(self, tmp_path):
        from initrunner.agent.executor import RunResult
        from initrunner.eval.runner import CaseResult, SuiteResult
        from initrunner.eval.schema import TestCase

        sr = SuiteResult(
            suite_name="save-test",
            case_results=[
                CaseResult(
                    case=TestCase(name="a", prompt="p"),
                    run_result=RunResult(run_id="r1", output="out"),
                    assertion_results=[],
                    passed=True,
                    duration_ms=100,
                ),
            ],
        )
        out = tmp_path / "results.json"
        save_result(sr, out)
        assert out.exists()
        data = json.loads(out.read_text())
        assert data["suite_name"] == "save-test"
        assert data["summary"]["total"] == 1

    def test_creates_parent_dirs(self, tmp_path):
        from initrunner.eval.runner import SuiteResult

        sr = SuiteResult(suite_name="test")
        out = tmp_path / "sub" / "dir" / "results.json"
        out.parent.mkdir(parents=True)
        save_result(sr, out)
        assert out.exists()
