"""Tests for eval LLM judge."""

import json
from unittest.mock import MagicMock, patch

from initrunner.eval.judge import (
    JudgeCriterionResult,
    JudgeResult,
    _get_judge_agent,
    _judge_cache,
    _parse_judge_response,
    run_judge_sync,
)


class TestParseJudgeResponse:
    def test_valid_json(self):
        response = json.dumps(
            {
                "results": [
                    {"criterion": "Is helpful", "passed": True, "reason": "Yes it is"},
                    {"criterion": "Is accurate", "passed": False, "reason": "Not quite"},
                ]
            }
        )
        result = _parse_judge_response(response, ["Is helpful", "Is accurate"])
        assert len(result.criteria_results) == 2
        assert result.criteria_results[0].passed is True
        assert result.criteria_results[1].passed is False
        assert not result.all_passed

    def test_all_passed(self):
        response = json.dumps(
            {
                "results": [
                    {"criterion": "c1", "passed": True, "reason": "ok"},
                    {"criterion": "c2", "passed": True, "reason": "ok"},
                ]
            }
        )
        result = _parse_judge_response(response, ["c1", "c2"])
        assert result.all_passed
        assert "2/2" in result.summary

    def test_malformed_json(self):
        result = _parse_judge_response("not json at all", ["c1", "c2"])
        assert len(result.criteria_results) == 2
        assert all(not cr.passed for cr in result.criteria_results)
        assert "parse error" in result.criteria_results[0].reason.lower()

    def test_partial_results_fills_missing(self):
        response = json.dumps(
            {
                "results": [
                    {"criterion": "c1", "passed": True, "reason": "ok"},
                ]
            }
        )
        result = _parse_judge_response(response, ["c1", "c2"])
        assert len(result.criteria_results) == 2
        assert result.criteria_results[0].passed is True
        # c2 should be marked as not evaluated
        c2 = next(cr for cr in result.criteria_results if cr.criterion == "c2")
        assert c2.passed is False
        assert "not evaluated" in c2.reason.lower()

    def test_empty_results_array(self):
        response = json.dumps({"results": []})
        result = _parse_judge_response(response, ["c1"])
        assert len(result.criteria_results) == 1
        assert not result.criteria_results[0].passed

    def test_missing_results_key(self):
        response = json.dumps({"something_else": True})
        result = _parse_judge_response(response, ["c1"])
        # Should still add the missing criterion
        assert len(result.criteria_results) == 1
        assert not result.criteria_results[0].passed


class TestJudgeResult:
    def test_all_passed_true(self):
        jr = JudgeResult(
            criteria_results=[
                JudgeCriterionResult(criterion="a", passed=True, reason="ok"),
                JudgeCriterionResult(criterion="b", passed=True, reason="ok"),
            ]
        )
        assert jr.all_passed is True

    def test_all_passed_false(self):
        jr = JudgeResult(
            criteria_results=[
                JudgeCriterionResult(criterion="a", passed=True, reason="ok"),
                JudgeCriterionResult(criterion="b", passed=False, reason="bad"),
            ]
        )
        assert jr.all_passed is False

    def test_summary(self):
        jr = JudgeResult(
            criteria_results=[
                JudgeCriterionResult(criterion="a", passed=True, reason="ok"),
                JudgeCriterionResult(criterion="b", passed=False, reason="bad"),
            ]
        )
        assert "1/2" in jr.summary

    def test_empty_results(self):
        jr = JudgeResult()
        assert jr.all_passed is True
        assert "0/0" in jr.summary


class TestGetJudgeAgent:
    def test_caching(self):
        from pydantic_ai.models.test import TestModel

        _judge_cache.clear()
        # Pre-populate with a TestModel to avoid needing real API keys
        model = TestModel()
        _judge_cache["test-model"] = model
        agent1 = _judge_cache["test-model"]
        agent2 = _judge_cache["test-model"]
        assert agent1 is agent2

    @patch("pydantic_ai.Agent")
    def test_creates_and_caches_agent(self, mock_agent_cls):
        _judge_cache.clear()
        mock_agent_cls.return_value = "agent-a"
        agent1 = _get_judge_agent("test:model-a")
        assert agent1 == "agent-a"
        # Second call should use cache, not create a new agent
        agent2 = _get_judge_agent("test:model-a")
        assert agent2 == "agent-a"
        mock_agent_cls.assert_called_once()

    @patch("pydantic_ai.Agent")
    def test_different_models_different_agents(self, mock_agent_cls):
        _judge_cache.clear()
        mock_agent_cls.side_effect = lambda *a, **kw: object()
        agent1 = _get_judge_agent("test:model-a")
        agent2 = _get_judge_agent("test:model-b")
        assert agent1 is not agent2
        assert mock_agent_cls.call_count == 2


class TestRunJudgeSync:
    @patch("initrunner.eval.judge._get_judge_agent")
    def test_calls_agent_and_parses(self, mock_get_agent):
        mock_agent = MagicMock()
        mock_result = MagicMock()
        mock_result.output = json.dumps(
            {
                "results": [
                    {"criterion": "Is good", "passed": True, "reason": "Yes"},
                ]
            }
        )
        mock_agent.run_sync.return_value = mock_result
        mock_get_agent.return_value = mock_agent

        result = run_judge_sync("test output", ["Is good"], model="openai:test")
        assert result.all_passed
        mock_get_agent.assert_called_once_with("openai:test")
        mock_agent.run_sync.assert_called_once()
        prompt_arg = mock_agent.run_sync.call_args[0][0]
        assert "test output" in prompt_arg
        assert "Is good" in prompt_arg
