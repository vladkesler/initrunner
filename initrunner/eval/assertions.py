"""Pure-function assertion evaluators for test suite outputs."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from initrunner.eval.schema import (
    Assertion,
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


@dataclass
class EvalContext:
    output: str
    tool_call_names: list[str] = field(default_factory=list)
    total_tokens: int = 0
    duration_ms: int = 0
    reasoning_tokens: int = 0
    event_timeline: list[dict[str, Any]] = field(default_factory=list)


def timeline_tool_calls(event_timeline: list[dict[str, Any]]) -> list[str]:
    """Return tool names in call order from a run-event timeline.

    Reads ``function_tool_call`` entries (see
    ``initrunner.agent.executor_output.build_timeline_entry``) and preserves the
    order they were emitted, so callers can reason about tool-call sequence
    rather than just presence.
    """
    return [
        entry["tool_name"]
        for entry in event_timeline
        if entry.get("type") == "function_tool_call" and entry.get("tool_name")
    ]


@dataclass
class AssertionResult:
    assertion: Assertion
    passed: bool
    message: str


def evaluate_assertion(
    assertion: Assertion, ctx: EvalContext, *, dry_run: bool = False
) -> AssertionResult:
    """Evaluate a single assertion against an EvalContext."""
    if isinstance(assertion, ContainsAssertion):
        haystack = ctx.output.lower() if assertion.case_insensitive else ctx.output
        needle = assertion.value.lower() if assertion.case_insensitive else assertion.value
        passed = needle in haystack
        if passed:
            message = f"Output contains '{assertion.value}'"
        else:
            message = f"Output does not contain '{assertion.value}'"
        return AssertionResult(assertion=assertion, passed=passed, message=message)

    if isinstance(assertion, NotContainsAssertion):
        haystack = ctx.output.lower() if assertion.case_insensitive else ctx.output
        needle = assertion.value.lower() if assertion.case_insensitive else assertion.value
        passed = needle not in haystack
        if passed:
            message = f"Output does not contain '{assertion.value}'"
        else:
            message = f"Output contains '{assertion.value}' (unexpected)"
        return AssertionResult(assertion=assertion, passed=passed, message=message)

    if isinstance(assertion, RegexAssertion):
        passed = re.search(assertion.pattern, ctx.output) is not None
        if passed:
            message = f"Output matches pattern '{assertion.pattern}'"
        else:
            message = f"Output does not match pattern '{assertion.pattern}'"
        return AssertionResult(assertion=assertion, passed=passed, message=message)

    if isinstance(assertion, ToolCallsAssertion):
        return _evaluate_tool_calls(assertion, ctx)

    if isinstance(assertion, MaxTokensAssertion):
        passed = ctx.total_tokens <= assertion.limit
        if passed:
            message = f"Tokens {ctx.total_tokens} within limit {assertion.limit}"
        else:
            message = f"Tokens {ctx.total_tokens} exceeded limit {assertion.limit}"
        return AssertionResult(assertion=assertion, passed=passed, message=message)

    if isinstance(assertion, MaxLatencyAssertion):
        passed = ctx.duration_ms <= assertion.limit_ms
        if passed:
            message = f"Latency {ctx.duration_ms}ms within limit {assertion.limit_ms}ms"
        else:
            message = f"Latency {ctx.duration_ms}ms exceeded limit {assertion.limit_ms}ms"
        return AssertionResult(assertion=assertion, passed=passed, message=message)

    if isinstance(assertion, ToolOrderAssertion):
        return _evaluate_tool_order(assertion, ctx)

    if isinstance(assertion, ReasoningBudgetAssertion):
        passed = ctx.reasoning_tokens <= assertion.max_reasoning_tokens
        if passed:
            message = (
                f"Reasoning tokens {ctx.reasoning_tokens} within budget "
                f"{assertion.max_reasoning_tokens}"
            )
        else:
            message = (
                f"Reasoning tokens {ctx.reasoning_tokens} exceeded budget "
                f"{assertion.max_reasoning_tokens}"
            )
        return AssertionResult(assertion=assertion, passed=passed, message=message)

    if isinstance(assertion, MemoryConsultedAssertion):
        return _evaluate_memory_consulted(assertion, ctx)

    if isinstance(assertion, SpanAssertion):
        return _evaluate_span(assertion, ctx)

    if isinstance(assertion, LLMJudgeAssertion):
        return _evaluate_llm_judge(assertion, ctx, dry_run=dry_run)

    return AssertionResult(assertion=assertion, passed=False, message="Unknown assertion type")


def _evaluate_tool_order(assertion: ToolOrderAssertion, ctx: EvalContext) -> AssertionResult:
    """Check the relative or exact order of tool calls in the run-event timeline."""
    observed = timeline_tool_calls(ctx.event_timeline)
    observed_str = ", ".join(observed) or "(none)"
    expected_str = ", ".join(assertion.sequence) or "(none)"

    if assertion.strict:
        passed = observed == assertion.sequence
        mode = "strict"
    else:
        passed = _is_subsequence(assertion.sequence, observed)
        mode = "relative"

    message = f"Tool order [{mode}]: expected=[{expected_str}], observed=[{observed_str}]"
    return AssertionResult(assertion=assertion, passed=passed, message=message)


def _is_subsequence(needle: list[str], haystack: list[str]) -> bool:
    """Return True when *needle* appears in *haystack* in order, gaps allowed."""
    it = iter(haystack)
    return all(item in it for item in needle)


def _evaluate_memory_consulted(
    assertion: MemoryConsultedAssertion, ctx: EvalContext
) -> AssertionResult:
    """Check whether memory tools were (or were not) called during the run."""
    memory_names = set(assertion.tools)
    called = [name for name in timeline_tool_calls(ctx.event_timeline) if name in memory_names]
    consulted = bool(called)
    passed = consulted == assertion.expected

    called_str = ", ".join(sorted(set(called))) or "(none)"
    if assertion.expected:
        message = f"Memory consulted: expected yes, observed [{called_str}]"
    else:
        message = f"Memory consulted: expected no, observed [{called_str}]"
    return AssertionResult(assertion=assertion, passed=passed, message=message)


def _evaluate_span(assertion: SpanAssertion, ctx: EvalContext) -> AssertionResult:
    """Match span-like records from the run-event timeline.

    The timeline is the always-available source: ``function_tool_call`` entries
    are treated as spans named after the tool, with their entry keys exposed as
    attributes. OTel span trees, when recorded, are consulted by the
    pydantic-evals span evaluator instead (see ``eval.evaluators``).
    """
    matches = [entry for entry in ctx.event_timeline if _entry_matches_span(entry, assertion)]
    count = len(matches)

    if assertion.count is None:
        passed = count > 0
    else:
        passed = count == assertion.count

    target = "any" if assertion.count is None else str(assertion.count)
    message = f"Span match: found {count} (expected {target})"
    return AssertionResult(assertion=assertion, passed=passed, message=message)


def _entry_matches_span(entry: dict[str, Any], assertion: SpanAssertion) -> bool:
    """Return True when a timeline *entry* satisfies a span assertion."""
    if assertion.name_contains is not None:
        name = str(entry.get("tool_name") or entry.get("type") or "")
        if assertion.name_contains not in name:
            return False
    if assertion.attribute is not None:
        if assertion.attribute not in entry:
            return False
        if assertion.attribute_value is not None:
            if str(entry.get(assertion.attribute)) != assertion.attribute_value:
                return False
    return True


def _evaluate_tool_calls(assertion: ToolCallsAssertion, ctx: EvalContext) -> AssertionResult:
    """Evaluate tool call assertions with F1 score reporting."""
    actual = set(ctx.tool_call_names)
    expected = set(assertion.expected)

    if assertion.mode == "exact":
        passed = actual == expected
    elif assertion.mode == "subset":
        # All expected must appear in actual
        passed = expected.issubset(actual)
    else:  # superset
        # Actual must be subset of expected (no unexpected tools)
        passed = actual.issubset(expected)

    # Compute precision/recall for reporting
    if not expected and not actual:
        precision = recall = 1.0
    elif not expected:
        precision = 0.0
        recall = 1.0
    elif not actual:
        precision = 1.0
        recall = 0.0
    else:
        true_positives = len(actual & expected)
        precision = true_positives / len(actual) if actual else 0.0
        recall = true_positives / len(expected) if expected else 0.0

    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

    actual_str = ", ".join(sorted(actual)) or "(none)"
    expected_str = ", ".join(sorted(expected)) or "(none)"
    message = (
        f"Tool calls [{assertion.mode}]: expected=[{expected_str}], "
        f"actual=[{actual_str}] (F1={f1:.2f})"
    )
    return AssertionResult(assertion=assertion, passed=passed, message=message)


def _evaluate_llm_judge(
    assertion: LLMJudgeAssertion, ctx: EvalContext, *, dry_run: bool = False
) -> AssertionResult:
    """Evaluate LLM judge assertions, skipping in dry-run mode."""
    if dry_run:
        return AssertionResult(
            assertion=assertion,
            passed=False,
            message="[skipped] LLM judge not run in dry-run mode",
        )

    from initrunner.eval.judge import run_judge_sync

    judge_result = run_judge_sync(ctx.output, assertion.criteria, model=assertion.model)
    return AssertionResult(
        assertion=assertion,
        passed=judge_result.all_passed,
        message=judge_result.summary,
    )


def evaluate_assertions(
    assertions: list[Assertion], ctx: EvalContext, *, dry_run: bool = False
) -> list[AssertionResult]:
    """Evaluate all assertions against an EvalContext."""
    return [evaluate_assertion(a, ctx, dry_run=dry_run) for a in assertions]
