"""Pure-function assertion evaluators for test suite outputs."""

from __future__ import annotations

import re
from dataclasses import dataclass

from initrunner.eval.schema import (
    Assertion,
    ContainsAssertion,
    NotContainsAssertion,
    RegexAssertion,
)


@dataclass
class AssertionResult:
    assertion: Assertion
    passed: bool
    message: str


def evaluate_assertion(assertion: Assertion, output: str) -> AssertionResult:
    """Evaluate a single assertion against output text."""
    if isinstance(assertion, ContainsAssertion):
        haystack = output.lower() if assertion.case_insensitive else output
        needle = assertion.value.lower() if assertion.case_insensitive else assertion.value
        passed = needle in haystack
        if passed:
            message = f"Output contains '{assertion.value}'"
        else:
            message = f"Output does not contain '{assertion.value}'"
        return AssertionResult(assertion=assertion, passed=passed, message=message)

    if isinstance(assertion, NotContainsAssertion):
        haystack = output.lower() if assertion.case_insensitive else output
        needle = assertion.value.lower() if assertion.case_insensitive else assertion.value
        passed = needle not in haystack
        if passed:
            message = f"Output does not contain '{assertion.value}'"
        else:
            message = f"Output contains '{assertion.value}' (unexpected)"
        return AssertionResult(assertion=assertion, passed=passed, message=message)

    if isinstance(assertion, RegexAssertion):
        passed = re.search(assertion.pattern, output) is not None
        if passed:
            message = f"Output matches pattern '{assertion.pattern}'"
        else:
            message = f"Output does not match pattern '{assertion.pattern}'"
        return AssertionResult(assertion=assertion, passed=passed, message=message)

    return AssertionResult(assertion=assertion, passed=False, message="Unknown assertion type")


def evaluate_assertions(assertions: list[Assertion], output: str) -> list[AssertionResult]:
    """Evaluate all assertions against output text."""
    return [evaluate_assertion(a, output) for a in assertions]
