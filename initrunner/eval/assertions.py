"""Pure-function assertion evaluators for test suite outputs."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from initrunner.eval.schema import (
    Assertion,
    ContainsAssertion,
    LLMJudgeAssertion,
    MaxLatencyAssertion,
    MaxTokensAssertion,
    NotContainsAssertion,
    RegexAssertion,
    ToolCallsAssertion,
)


@dataclass
class EvalContext:
    output: str
    tool_call_names: list[str] = field(default_factory=list)
    total_tokens: int = 0
    duration_ms: int = 0


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

    if isinstance(assertion, LLMJudgeAssertion):
        return _evaluate_llm_judge(assertion, ctx, dry_run=dry_run)

    return AssertionResult(assertion=assertion, passed=False, message="Unknown assertion type")


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
