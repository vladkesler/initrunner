"""Tests for eval assertion evaluators."""

from initrunner.eval.assertions import evaluate_assertion, evaluate_assertions
from initrunner.eval.schema import ContainsAssertion, NotContainsAssertion, RegexAssertion


class TestContainsAssertion:
    def test_passes_when_present(self):
        a = ContainsAssertion(value="hello")
        result = evaluate_assertion(a, "hello world")
        assert result.passed is True

    def test_fails_when_absent(self):
        a = ContainsAssertion(value="goodbye")
        result = evaluate_assertion(a, "hello world")
        assert result.passed is False

    def test_case_sensitive_by_default(self):
        a = ContainsAssertion(value="Hello")
        result = evaluate_assertion(a, "hello world")
        assert result.passed is False

    def test_case_insensitive(self):
        a = ContainsAssertion(value="Hello", case_insensitive=True)
        result = evaluate_assertion(a, "hello world")
        assert result.passed is True

    def test_message_on_pass(self):
        a = ContainsAssertion(value="hi")
        result = evaluate_assertion(a, "hi there")
        assert "contains" in result.message.lower()
        assert "hi" in result.message

    def test_message_on_fail(self):
        a = ContainsAssertion(value="missing")
        result = evaluate_assertion(a, "hello")
        assert "does not contain" in result.message.lower()


class TestNotContainsAssertion:
    def test_passes_when_absent(self):
        a = NotContainsAssertion(value="error")
        result = evaluate_assertion(a, "all good")
        assert result.passed is True

    def test_fails_when_present(self):
        a = NotContainsAssertion(value="error")
        result = evaluate_assertion(a, "an error occurred")
        assert result.passed is False

    def test_case_sensitive_by_default(self):
        a = NotContainsAssertion(value="Error")
        result = evaluate_assertion(a, "error occurred")
        assert result.passed is True

    def test_case_insensitive(self):
        a = NotContainsAssertion(value="Error", case_insensitive=True)
        result = evaluate_assertion(a, "error occurred")
        assert result.passed is False

    def test_message_on_fail(self):
        a = NotContainsAssertion(value="bad")
        result = evaluate_assertion(a, "bad stuff")
        assert "unexpected" in result.message.lower()


class TestRegexAssertion:
    def test_passes_on_match(self):
        a = RegexAssertion(pattern=r"\b4\b")
        result = evaluate_assertion(a, "The answer is 4.")
        assert result.passed is True

    def test_fails_on_no_match(self):
        a = RegexAssertion(pattern=r"\b4\b")
        result = evaluate_assertion(a, "The answer is five.")
        assert result.passed is False

    def test_complex_pattern(self):
        a = RegexAssertion(pattern=r"\d{3}-\d{4}")
        result = evaluate_assertion(a, "Call 555-1234")
        assert result.passed is True

    def test_message_references_pattern(self):
        a = RegexAssertion(pattern=r"\d+")
        result = evaluate_assertion(a, "no numbers")
        assert a.pattern in result.message


class TestEvaluateAssertions:
    def test_all_pass(self):
        assertions = [
            ContainsAssertion(value="hello"),
            NotContainsAssertion(value="error"),
        ]
        results = evaluate_assertions(assertions, "hello world")
        assert all(r.passed for r in results)
        assert len(results) == 2

    def test_mixed_results(self):
        assertions = [
            ContainsAssertion(value="hello"),
            ContainsAssertion(value="missing"),
        ]
        results = evaluate_assertions(assertions, "hello world")
        assert results[0].passed is True
        assert results[1].passed is False

    def test_empty_assertions(self):
        results = evaluate_assertions([], "anything")
        assert results == []

    def test_preserves_assertion_reference(self):
        a = ContainsAssertion(value="x")
        results = evaluate_assertions([a], "x marks the spot")
        assert results[0].assertion is a
