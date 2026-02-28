"""Tests for eval assertion evaluators."""

from unittest.mock import patch

from initrunner.eval.assertions import (
    EvalContext,
    evaluate_assertion,
    evaluate_assertions,
)
from initrunner.eval.schema import (
    ContainsAssertion,
    LLMJudgeAssertion,
    MaxLatencyAssertion,
    MaxTokensAssertion,
    NotContainsAssertion,
    RegexAssertion,
    ToolCallsAssertion,
)


class TestEvalContext:
    def test_defaults(self):
        ctx = EvalContext(output="hello")
        assert ctx.output == "hello"
        assert ctx.tool_call_names == []
        assert ctx.total_tokens == 0
        assert ctx.duration_ms == 0

    def test_with_all_fields(self):
        ctx = EvalContext(
            output="result",
            tool_call_names=["search", "read"],
            total_tokens=150,
            duration_ms=3000,
        )
        assert ctx.tool_call_names == ["search", "read"]
        assert ctx.total_tokens == 150
        assert ctx.duration_ms == 3000


class TestContainsAssertion:
    def test_passes_when_present(self):
        a = ContainsAssertion(value="hello")
        result = evaluate_assertion(a, EvalContext(output="hello world"))
        assert result.passed is True

    def test_fails_when_absent(self):
        a = ContainsAssertion(value="goodbye")
        result = evaluate_assertion(a, EvalContext(output="hello world"))
        assert result.passed is False

    def test_case_sensitive_by_default(self):
        a = ContainsAssertion(value="Hello")
        result = evaluate_assertion(a, EvalContext(output="hello world"))
        assert result.passed is False

    def test_case_insensitive(self):
        a = ContainsAssertion(value="Hello", case_insensitive=True)
        result = evaluate_assertion(a, EvalContext(output="hello world"))
        assert result.passed is True

    def test_message_on_pass(self):
        a = ContainsAssertion(value="hi")
        result = evaluate_assertion(a, EvalContext(output="hi there"))
        assert "contains" in result.message.lower()
        assert "hi" in result.message

    def test_message_on_fail(self):
        a = ContainsAssertion(value="missing")
        result = evaluate_assertion(a, EvalContext(output="hello"))
        assert "does not contain" in result.message.lower()


class TestNotContainsAssertion:
    def test_passes_when_absent(self):
        a = NotContainsAssertion(value="error")
        result = evaluate_assertion(a, EvalContext(output="all good"))
        assert result.passed is True

    def test_fails_when_present(self):
        a = NotContainsAssertion(value="error")
        result = evaluate_assertion(a, EvalContext(output="an error occurred"))
        assert result.passed is False

    def test_case_sensitive_by_default(self):
        a = NotContainsAssertion(value="Error")
        result = evaluate_assertion(a, EvalContext(output="error occurred"))
        assert result.passed is True

    def test_case_insensitive(self):
        a = NotContainsAssertion(value="Error", case_insensitive=True)
        result = evaluate_assertion(a, EvalContext(output="error occurred"))
        assert result.passed is False

    def test_message_on_fail(self):
        a = NotContainsAssertion(value="bad")
        result = evaluate_assertion(a, EvalContext(output="bad stuff"))
        assert "unexpected" in result.message.lower()


class TestRegexAssertion:
    def test_passes_on_match(self):
        a = RegexAssertion(pattern=r"\b4\b")
        result = evaluate_assertion(a, EvalContext(output="The answer is 4."))
        assert result.passed is True

    def test_fails_on_no_match(self):
        a = RegexAssertion(pattern=r"\b4\b")
        result = evaluate_assertion(a, EvalContext(output="The answer is five."))
        assert result.passed is False

    def test_complex_pattern(self):
        a = RegexAssertion(pattern=r"\d{3}-\d{4}")
        result = evaluate_assertion(a, EvalContext(output="Call 555-1234"))
        assert result.passed is True

    def test_message_references_pattern(self):
        a = RegexAssertion(pattern=r"\d+")
        result = evaluate_assertion(a, EvalContext(output="no numbers"))
        assert a.pattern in result.message


class TestToolCallsAssertion:
    def test_subset_passes_when_all_expected_present(self):
        a = ToolCallsAssertion(expected=["search"], mode="subset")
        ctx = EvalContext(output="", tool_call_names=["search", "read"])
        result = evaluate_assertion(a, ctx)
        assert result.passed is True

    def test_subset_fails_when_expected_missing(self):
        a = ToolCallsAssertion(expected=["search", "write"], mode="subset")
        ctx = EvalContext(output="", tool_call_names=["search"])
        result = evaluate_assertion(a, ctx)
        assert result.passed is False

    def test_exact_passes_when_sets_match(self):
        a = ToolCallsAssertion(expected=["search", "read"], mode="exact")
        ctx = EvalContext(output="", tool_call_names=["read", "search"])
        result = evaluate_assertion(a, ctx)
        assert result.passed is True

    def test_exact_fails_with_extra(self):
        a = ToolCallsAssertion(expected=["search"], mode="exact")
        ctx = EvalContext(output="", tool_call_names=["search", "read"])
        result = evaluate_assertion(a, ctx)
        assert result.passed is False

    def test_exact_fails_with_missing(self):
        a = ToolCallsAssertion(expected=["search", "read"], mode="exact")
        ctx = EvalContext(output="", tool_call_names=["search"])
        result = evaluate_assertion(a, ctx)
        assert result.passed is False

    def test_superset_passes_when_no_unexpected(self):
        a = ToolCallsAssertion(expected=["search", "read", "write"], mode="superset")
        ctx = EvalContext(output="", tool_call_names=["search", "read"])
        result = evaluate_assertion(a, ctx)
        assert result.passed is True

    def test_superset_fails_with_unexpected(self):
        a = ToolCallsAssertion(expected=["search"], mode="superset")
        ctx = EvalContext(output="", tool_call_names=["search", "read"])
        result = evaluate_assertion(a, ctx)
        assert result.passed is False

    def test_f1_score_in_message(self):
        a = ToolCallsAssertion(expected=["search"], mode="subset")
        ctx = EvalContext(output="", tool_call_names=["search"])
        result = evaluate_assertion(a, ctx)
        assert "F1=" in result.message

    def test_empty_expected_empty_actual(self):
        a = ToolCallsAssertion(expected=[], mode="exact")
        ctx = EvalContext(output="", tool_call_names=[])
        result = evaluate_assertion(a, ctx)
        assert result.passed is True
        assert "F1=1.00" in result.message

    def test_empty_expected_with_actual(self):
        a = ToolCallsAssertion(expected=[], mode="exact")
        ctx = EvalContext(output="", tool_call_names=["search"])
        result = evaluate_assertion(a, ctx)
        assert result.passed is False

    def test_duplicates_in_actual_use_set(self):
        a = ToolCallsAssertion(expected=["search"], mode="subset")
        ctx = EvalContext(output="", tool_call_names=["search", "search", "search"])
        result = evaluate_assertion(a, ctx)
        assert result.passed is True


class TestMaxTokensAssertion:
    def test_passes_under_limit(self):
        a = MaxTokensAssertion(limit=1000)
        ctx = EvalContext(output="", total_tokens=500)
        result = evaluate_assertion(a, ctx)
        assert result.passed is True
        assert "within limit" in result.message

    def test_passes_at_limit(self):
        a = MaxTokensAssertion(limit=1000)
        ctx = EvalContext(output="", total_tokens=1000)
        result = evaluate_assertion(a, ctx)
        assert result.passed is True

    def test_fails_over_limit(self):
        a = MaxTokensAssertion(limit=1000)
        ctx = EvalContext(output="", total_tokens=1001)
        result = evaluate_assertion(a, ctx)
        assert result.passed is False
        assert "exceeded" in result.message


class TestMaxLatencyAssertion:
    def test_passes_under_limit(self):
        a = MaxLatencyAssertion(limit_ms=5000)
        ctx = EvalContext(output="", duration_ms=3000)
        result = evaluate_assertion(a, ctx)
        assert result.passed is True
        assert "within limit" in result.message

    def test_passes_at_limit(self):
        a = MaxLatencyAssertion(limit_ms=5000)
        ctx = EvalContext(output="", duration_ms=5000)
        result = evaluate_assertion(a, ctx)
        assert result.passed is True

    def test_fails_over_limit(self):
        a = MaxLatencyAssertion(limit_ms=5000)
        ctx = EvalContext(output="", duration_ms=6000)
        result = evaluate_assertion(a, ctx)
        assert result.passed is False
        assert "exceeded" in result.message


class TestLLMJudgeAssertion:
    def test_dry_run_skips(self):
        a = LLMJudgeAssertion(criteria=["Is helpful"])
        ctx = EvalContext(output="hello")
        result = evaluate_assertion(a, ctx, dry_run=True)
        assert result.passed is False
        assert "[skipped]" in result.message

    @patch("initrunner.eval.judge.run_judge_sync")
    def test_calls_judge(self, mock_judge):
        from initrunner.eval.judge import JudgeCriterionResult, JudgeResult

        mock_judge.return_value = JudgeResult(
            criteria_results=[
                JudgeCriterionResult(criterion="Is helpful", passed=True, reason="Yes"),
            ]
        )
        a = LLMJudgeAssertion(criteria=["Is helpful"])
        ctx = EvalContext(output="helpful response")
        result = evaluate_assertion(a, ctx)
        assert result.passed is True
        mock_judge.assert_called_once_with(
            "helpful response", ["Is helpful"], model="openai:gpt-4o-mini"
        )

    @patch("initrunner.eval.judge.run_judge_sync")
    def test_judge_fails(self, mock_judge):
        from initrunner.eval.judge import JudgeCriterionResult, JudgeResult

        mock_judge.return_value = JudgeResult(
            criteria_results=[
                JudgeCriterionResult(criterion="Is helpful", passed=False, reason="Not helpful"),
            ]
        )
        a = LLMJudgeAssertion(criteria=["Is helpful"])
        ctx = EvalContext(output="bad response")
        result = evaluate_assertion(a, ctx)
        assert result.passed is False


class TestEvaluateAssertions:
    def test_all_pass(self):
        assertions = [
            ContainsAssertion(value="hello"),
            NotContainsAssertion(value="error"),
        ]
        results = evaluate_assertions(assertions, EvalContext(output="hello world"))
        assert all(r.passed for r in results)
        assert len(results) == 2

    def test_mixed_results(self):
        assertions = [
            ContainsAssertion(value="hello"),
            ContainsAssertion(value="missing"),
        ]
        results = evaluate_assertions(assertions, EvalContext(output="hello world"))
        assert results[0].passed is True
        assert results[1].passed is False

    def test_empty_assertions(self):
        results = evaluate_assertions([], EvalContext(output="anything"))
        assert results == []

    def test_preserves_assertion_reference(self):
        a = ContainsAssertion(value="x")
        results = evaluate_assertions([a], EvalContext(output="x marks the spot"))
        assert results[0].assertion is a

    def test_dry_run_passed_through(self):
        assertions = [LLMJudgeAssertion(criteria=["Is good"])]
        results = evaluate_assertions(assertions, EvalContext(output="output"), dry_run=True)
        assert results[0].passed is False
        assert "[skipped]" in results[0].message
