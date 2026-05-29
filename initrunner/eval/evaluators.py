"""pydantic-evals Evaluator adapters backed by the InitRunner assertion logic.

This module is imported only on the opt-in pydantic-evals path
(``run_suite(..., enable_pydantic_evals=True)``). It depends on the
``pydantic-evals`` package, which ships in the ``observability`` extra. Importing
it without the extra installed raises ``MissingExtraError`` with an install hint.

Each adapter reuses the pure assertion functions in
:mod:`initrunner.eval.assertions` so the bespoke runner and the pydantic-evals
runner agree on pass/fail semantics. The task output handed to evaluators is a
:class:`RunRecord` carrying the agent output plus the structured run-event
timeline and token counts captured during execution. Span-based assertions
prefer a real OTel ``SpanTree`` (``ctx.span_tree``) when one was recorded and
fall back to the run-event timeline otherwise.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from initrunner._compat import require_extra
from initrunner.eval.assertions import (
    EvalContext,
    timeline_tool_calls,
)
from initrunner.eval.schema import (
    ContainsAssertion,
    LLMJudgeAssertion,
    MaxLatencyAssertion,
    MaxTokensAssertion,
    MemoryConsultedAssertion,
    NotContainsAssertion,
    ReasoningBudgetAssertion,
    RegexAssertion,
    SpanAssertion,
    ToolCallsAssertion,
    ToolOrderAssertion,
)

require_extra("pydantic_evals", extra="observability", pip_name="pydantic-evals")

from pydantic_evals.evaluators import (  # type: ignore[import-not-found]  # noqa: E402
    EvaluationReason,
    Evaluator,
    EvaluatorContext,
)

if TYPE_CHECKING:
    from initrunner.eval.schema import Assertion


@dataclass
class RunRecord:
    """Task output handed to evaluators on the pydantic-evals path.

    Carries everything the assertion functions need beyond the OTel span tree:
    the final text output, tool-call names, token and reasoning-token counts, the
    measured duration, and the redacted run-event timeline from item 3.
    """

    output: str = ""
    tool_call_names: list[str] = field(default_factory=list)
    total_tokens: int = 0
    reasoning_tokens: int = 0
    duration_ms: int = 0
    event_timeline: list[dict[str, Any]] = field(default_factory=list)


def _eval_context_from_output(output: RunRecord) -> EvalContext:
    return EvalContext(
        output=output.output,
        tool_call_names=output.tool_call_names,
        total_tokens=output.total_tokens,
        duration_ms=output.duration_ms,
        reasoning_tokens=output.reasoning_tokens,
        event_timeline=output.event_timeline,
    )


@dataclass
class AssertionEvaluator(Evaluator[Any, RunRecord, Any]):
    """Generic adapter that runs one InitRunner assertion via the shared logic.

    Handles every output- and timeline-based assertion type. Span assertions use
    :class:`SpanAssertionEvaluator` instead because they also consult the OTel
    span tree.
    """

    assertion: Assertion

    def evaluate(self, ctx: EvaluatorContext[Any, RunRecord, Any]) -> dict[str, EvaluationReason]:
        from initrunner.eval.assertions import evaluate_assertion

        eval_ctx = _eval_context_from_output(ctx.output)
        result = evaluate_assertion(self.assertion, eval_ctx)
        return {
            self.assertion.type: EvaluationReason(value=result.passed, reason=result.message),
        }


@dataclass
class SpanAssertionEvaluator(Evaluator[Any, RunRecord, Any]):
    """Span assertion that prefers the OTel span tree, falling back to the timeline.

    When a ``SpanTree`` was recorded for the run it is queried first; otherwise
    the run-event timeline is matched by the same predicate via the shared
    assertion logic.
    """

    assertion: SpanAssertion

    def evaluate(self, ctx: EvaluatorContext[Any, RunRecord, Any]) -> dict[str, EvaluationReason]:
        tree = _safe_span_tree(ctx)
        if tree is not None:
            passed, message = _match_span_tree(self.assertion, tree)
            return {"span": EvaluationReason(value=passed, reason=message)}

        from initrunner.eval.assertions import evaluate_assertion

        eval_ctx = _eval_context_from_output(ctx.output)
        result = evaluate_assertion(self.assertion, eval_ctx)
        return {"span": EvaluationReason(value=result.passed, reason=result.message)}


def _safe_span_tree(ctx: EvaluatorContext[Any, RunRecord, Any]) -> Any:
    """Return the recorded ``SpanTree`` or ``None`` when none was captured."""
    try:
        return ctx.span_tree
    except Exception:
        return None


def _match_span_tree(assertion: SpanAssertion, tree: Any) -> tuple[bool, str]:
    """Query an OTel ``SpanTree`` for spans matching *assertion*."""
    query: dict[str, Any] = {}
    if assertion.name_contains is not None:
        query["name_contains"] = assertion.name_contains
    if assertion.attribute is not None:
        if assertion.attribute_value is not None:
            query["has_attributes"] = {assertion.attribute: assertion.attribute_value}
        else:
            query["has_attribute_keys"] = [assertion.attribute]

    matches = tree.find(query) if query else tree.find({})
    count = len(matches)
    if assertion.count is None:
        passed = count > 0
    else:
        passed = count == assertion.count
    target = "any" if assertion.count is None else str(assertion.count)
    return passed, f"Span match (otel): found {count} (expected {target})"


# Assertion types that the generic AssertionEvaluator covers directly.
_GENERIC_ASSERTION_TYPES = (
    ContainsAssertion,
    NotContainsAssertion,
    RegexAssertion,
    LLMJudgeAssertion,
    ToolCallsAssertion,
    MaxTokensAssertion,
    MaxLatencyAssertion,
    ToolOrderAssertion,
    ReasoningBudgetAssertion,
    MemoryConsultedAssertion,
)


def build_evaluators(assertions: list[Assertion]) -> list[Evaluator[Any, RunRecord, Any]]:
    """Translate a list of InitRunner assertions into pydantic-evals evaluators."""
    evaluators: list[Evaluator[Any, RunRecord, Any]] = []
    for assertion in assertions:
        if isinstance(assertion, SpanAssertion):
            evaluators.append(SpanAssertionEvaluator(assertion=assertion))
        elif isinstance(assertion, _GENERIC_ASSERTION_TYPES):
            evaluators.append(AssertionEvaluator(assertion=assertion))
        else:  # pragma: no cover - exhaustive over the Assertion union
            raise ValueError(f"Unsupported assertion type: {assertion.type}")
    return evaluators


__all__ = [
    "AssertionEvaluator",
    "RunRecord",
    "SpanAssertionEvaluator",
    "build_evaluators",
    "timeline_tool_calls",
]
