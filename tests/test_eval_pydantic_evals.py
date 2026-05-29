"""Tests for the pydantic-evals run-suite path and span-based assertions."""

from datetime import UTC, datetime

import pytest
from pydantic_ai import Agent
from pydantic_ai.models.test import TestModel

from initrunner.agent.schema.base import ApiVersion, Kind, ModelConfig, RoleMetadata
from initrunner.agent.schema.role import AgentSpec, RoleDefinition
from initrunner.eval.assertions import EvalContext, evaluate_assertion, timeline_tool_calls
from initrunner.eval.schema import (
    MemoryConsultedAssertion,
    ReasoningBudgetAssertion,
    SpanAssertion,
    TestSuiteDefinition,
    ToolOrderAssertion,
)

pytest.importorskip("pydantic_evals")


def _make_role() -> RoleDefinition:
    return RoleDefinition(
        apiVersion=ApiVersion.V1,
        kind=Kind.AGENT,
        metadata=RoleMetadata(name="test-agent"),
        spec=AgentSpec(
            role="You are a test.",
            model=ModelConfig(provider="openai", name="gpt-5-mini"),
        ),
    )


def _make_agent() -> Agent:
    return Agent(TestModel())


def _suite(cases: list[dict]) -> TestSuiteDefinition:
    return TestSuiteDefinition.model_validate(
        {
            "apiVersion": "initrunner/v1",
            "kind": "TestSuite",
            "metadata": {"name": "pe-suite"},
            "cases": cases,
        }
    )


_TIMELINE = [
    {"type": "function_tool_call", "tool_name": "search", "tool_call_id": "1"},
    {"type": "function_tool_result", "content_preview": "x"},
    {"type": "function_tool_call", "tool_name": "recall_memory", "tool_call_id": "2"},
    {"type": "function_tool_call", "tool_name": "write", "tool_call_id": "3"},
]


class TestTimelineToolCalls:
    def test_extracts_call_order(self):
        assert timeline_tool_calls(_TIMELINE) == ["search", "recall_memory", "write"]

    def test_ignores_non_call_entries(self):
        timeline = [{"type": "thinking_delta", "content_delta": "..."}]
        assert timeline_tool_calls(timeline) == []


class TestToolOrderAssertion:
    def test_relative_order_pass(self):
        ctx = EvalContext(output="", event_timeline=_TIMELINE)
        res = evaluate_assertion(ToolOrderAssertion(sequence=["search", "write"]), ctx)
        assert res.passed

    def test_relative_order_fail(self):
        ctx = EvalContext(output="", event_timeline=_TIMELINE)
        res = evaluate_assertion(ToolOrderAssertion(sequence=["write", "search"]), ctx)
        assert not res.passed

    def test_strict_order_fail_on_gap(self):
        ctx = EvalContext(output="", event_timeline=_TIMELINE)
        res = evaluate_assertion(ToolOrderAssertion(sequence=["search", "write"], strict=True), ctx)
        assert not res.passed

    def test_strict_order_pass_exact(self):
        ctx = EvalContext(output="", event_timeline=_TIMELINE)
        res = evaluate_assertion(
            ToolOrderAssertion(sequence=["search", "recall_memory", "write"], strict=True),
            ctx,
        )
        assert res.passed


class TestReasoningBudgetAssertion:
    def test_within_budget(self):
        ctx = EvalContext(output="", reasoning_tokens=50)
        res = evaluate_assertion(ReasoningBudgetAssertion(max_reasoning_tokens=100), ctx)
        assert res.passed

    def test_over_budget(self):
        ctx = EvalContext(output="", reasoning_tokens=200)
        res = evaluate_assertion(ReasoningBudgetAssertion(max_reasoning_tokens=100), ctx)
        assert not res.passed

    def test_zero_reasoning_always_passes(self):
        ctx = EvalContext(output="", reasoning_tokens=0)
        res = evaluate_assertion(ReasoningBudgetAssertion(max_reasoning_tokens=1), ctx)
        assert res.passed


class TestMemoryConsultedAssertion:
    def test_expected_yes_observed_yes(self):
        ctx = EvalContext(output="", event_timeline=_TIMELINE)
        res = evaluate_assertion(MemoryConsultedAssertion(expected=True), ctx)
        assert res.passed

    def test_expected_no_observed_yes_fails(self):
        ctx = EvalContext(output="", event_timeline=_TIMELINE)
        res = evaluate_assertion(MemoryConsultedAssertion(expected=False), ctx)
        assert not res.passed

    def test_expected_no_observed_no_passes(self):
        timeline = [{"type": "function_tool_call", "tool_name": "search"}]
        ctx = EvalContext(output="", event_timeline=timeline)
        res = evaluate_assertion(MemoryConsultedAssertion(expected=False), ctx)
        assert res.passed

    def test_custom_memory_tool_names(self):
        timeline = [{"type": "function_tool_call", "tool_name": "vector_lookup"}]
        ctx = EvalContext(output="", event_timeline=timeline)
        res = evaluate_assertion(
            MemoryConsultedAssertion(expected=True, tools=["vector_lookup"]), ctx
        )
        assert res.passed


class TestSpanAssertionTimelineFallback:
    def test_name_contains_count(self):
        ctx = EvalContext(output="", event_timeline=_TIMELINE)
        res = evaluate_assertion(SpanAssertion(name_contains="search", count=1), ctx)
        assert res.passed

    def test_name_contains_zero(self):
        ctx = EvalContext(output="", event_timeline=_TIMELINE)
        res = evaluate_assertion(SpanAssertion(name_contains="browser", count=0), ctx)
        assert res.passed

    def test_attribute_match(self):
        ctx = EvalContext(output="", event_timeline=_TIMELINE)
        res = evaluate_assertion(SpanAssertion(attribute="tool_call_id", attribute_value="2"), ctx)
        assert res.passed

    def test_attribute_value_mismatch(self):
        ctx = EvalContext(output="", event_timeline=_TIMELINE)
        res = evaluate_assertion(
            SpanAssertion(attribute="tool_call_id", attribute_value="999"), ctx
        )
        assert not res.passed


class TestBuildEvaluators:
    def test_maps_each_assertion_type(self):
        from initrunner.eval.evaluators import (
            AssertionEvaluator,
            SpanAssertionEvaluator,
            build_evaluators,
        )

        suite = _suite(
            [
                {
                    "name": "case",
                    "prompt": "p",
                    "assertions": [
                        {"type": "contains", "value": "x"},
                        {"type": "tool_order", "sequence": ["a"]},
                        {"type": "span", "name_contains": "search"},
                    ],
                }
            ]
        )
        evaluators = build_evaluators(suite.cases[0].assertions)
        assert isinstance(evaluators[0], AssertionEvaluator)
        assert isinstance(evaluators[1], AssertionEvaluator)
        assert isinstance(evaluators[2], SpanAssertionEvaluator)


class TestRunSuitePydanticEvals:
    def test_returns_suite_result_and_report(self):
        from initrunner.eval.runner import PydanticEvalsResult, run_suite_pydantic_evals

        suite = _suite(
            [
                {
                    "name": "c1",
                    "prompt": "hi",
                    "expected_output": "The answer is 4 hello",
                    "assertions": [
                        {"type": "contains", "value": "4"},
                        {"type": "contains", "value": "hello"},
                    ],
                }
            ]
        )
        result = run_suite_pydantic_evals(_make_agent(), _make_role(), suite, dry_run=True)
        assert isinstance(result, PydanticEvalsResult)
        assert result.suite_result.all_passed
        assert len(result.report.cases) == 1

    def test_failing_case_reported(self):
        from initrunner.eval.runner import run_suite_pydantic_evals

        suite = _suite(
            [
                {
                    "name": "c2",
                    "prompt": "x",
                    "expected_output": "nope",
                    "assertions": [{"type": "contains", "value": "MISSING"}],
                }
            ]
        )
        result = run_suite_pydantic_evals(_make_agent(), _make_role(), suite, dry_run=True)
        assert result.suite_result.failed == 1
        assert not result.suite_result.case_results[0].passed

    def test_duplicate_assertion_types_kept_distinct(self):
        from initrunner.eval.runner import run_suite_pydantic_evals

        suite = _suite(
            [
                {
                    "name": "c1",
                    "prompt": "hi",
                    "expected_output": "alpha beta",
                    "assertions": [
                        {"type": "contains", "value": "alpha"},
                        {"type": "contains", "value": "MISSING"},
                    ],
                }
            ]
        )
        result = run_suite_pydantic_evals(_make_agent(), _make_role(), suite, dry_run=True)
        cr = result.suite_result.case_results[0]
        assert len(cr.assertion_results) == 2
        assert cr.assertion_results[0].passed
        assert not cr.assertion_results[1].passed

    def test_empty_suite_returns_empty_result(self):
        from initrunner.eval.runner import run_suite_pydantic_evals

        suite = _suite([])
        result = run_suite_pydantic_evals(_make_agent(), _make_role(), suite, dry_run=True)
        assert result.suite_result.total == 0
        assert len(result.report.cases) == 0

    def test_tag_filter(self):
        from initrunner.eval.runner import run_suite_pydantic_evals

        suite = _suite(
            [
                {"name": "tagged", "prompt": "p1", "tags": ["fast"]},
                {"name": "untagged", "prompt": "p2"},
            ]
        )
        result = run_suite_pydantic_evals(
            _make_agent(), _make_role(), suite, dry_run=True, tag_filter=["fast"]
        )
        assert result.suite_result.total == 1
        assert result.suite_result.case_results[0].case.name == "tagged"

    def test_suite_result_to_dict_serializable(self):
        import json

        from initrunner.eval.runner import run_suite_pydantic_evals

        suite = _suite(
            [
                {
                    "name": "c1",
                    "prompt": "hi",
                    "expected_output": "hello there",
                    "assertions": [{"type": "contains", "value": "hello"}],
                }
            ]
        )
        result = run_suite_pydantic_evals(_make_agent(), _make_role(), suite, dry_run=True)
        d = result.suite_result.to_dict()
        assert d["summary"]["total"] == 1
        assert json.loads(json.dumps(d))["cases"][0]["assertions"][0]["type"] == "contains"


class TestSpanAssertionEvaluatorOtel:
    def test_prefers_span_tree_when_recorded(self):
        from pydantic_evals.evaluators import EvaluatorContext
        from pydantic_evals.otel.span_tree import SpanNode, SpanTree

        from initrunner.eval.evaluators import RunRecord, SpanAssertionEvaluator

        now = datetime.now(tz=UTC)
        tree = SpanTree()
        tree.add_spans(
            [
                SpanNode(
                    name="search-tool",
                    trace_id=1,
                    span_id=1,
                    parent_span_id=None,
                    start_timestamp=now,
                    end_timestamp=now,
                    attributes={"tool_name": "search"},
                )
            ]
        )
        ctx = EvaluatorContext(
            name="c",
            inputs={},
            metadata=None,
            expected_output=None,
            output=RunRecord(output="out"),
            duration=0.1,
            _span_tree=tree,
            attributes={},
            metrics={},
        )
        evaluator = SpanAssertionEvaluator(assertion=SpanAssertion(name_contains="search", count=1))
        result = evaluator.evaluate(ctx)
        assert result["span"].value is True
        reason = result["span"].reason
        assert reason is not None and "otel" in reason

    def test_falls_back_to_timeline_without_spans(self):
        from pydantic_evals.evaluators import EvaluatorContext
        from pydantic_evals.otel._errors import SpanTreeRecordingError

        from initrunner.eval.evaluators import RunRecord, SpanAssertionEvaluator

        ctx = EvaluatorContext(
            name="c",
            inputs={},
            metadata=None,
            expected_output=None,
            output=RunRecord(output="out", event_timeline=_TIMELINE),
            duration=0.1,
            _span_tree=SpanTreeRecordingError("no spans"),
            attributes={},
            metrics={},
        )
        evaluator = SpanAssertionEvaluator(assertion=SpanAssertion(name_contains="search", count=1))
        result = evaluator.evaluate(ctx)
        assert result["span"].value is True
        reason = result["span"].reason
        assert reason is not None and "otel" not in reason
