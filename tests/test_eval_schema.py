"""Tests for eval suite YAML schema parsing and validation."""

import pytest
from pydantic import ValidationError

from initrunner.eval.schema import (
    ContainsAssertion,
    NotContainsAssertion,
    RegexAssertion,
    TestCase,
    TestSuiteDefinition,
)


class TestTestSuiteDefinition:
    def test_minimal_suite(self):
        suite = TestSuiteDefinition.model_validate(
            {
                "apiVersion": "initrunner/v1",
                "kind": "TestSuite",
                "metadata": {"name": "minimal"},
                "cases": [],
            }
        )
        assert suite.metadata.name == "minimal"
        assert suite.cases == []

    def test_full_suite(self):
        suite = TestSuiteDefinition.model_validate(
            {
                "apiVersion": "initrunner/v1",
                "kind": "TestSuite",
                "metadata": {"name": "full-test"},
                "cases": [
                    {
                        "name": "greeting",
                        "prompt": "Hello!",
                        "assertions": [
                            {"type": "contains", "value": "hello", "case_insensitive": True},
                            {"type": "not_contains", "value": "error"},
                        ],
                    },
                    {
                        "name": "math",
                        "prompt": "What is 2+2?",
                        "expected_output": "4",
                        "assertions": [
                            {"type": "regex", "pattern": r"\b4\b"},
                        ],
                    },
                ],
            }
        )
        assert suite.metadata.name == "full-test"
        assert len(suite.cases) == 2
        assert suite.cases[0].name == "greeting"
        assert len(suite.cases[0].assertions) == 2
        assert suite.cases[1].expected_output == "4"

    def test_invalid_kind_rejected(self):
        with pytest.raises(ValidationError):
            TestSuiteDefinition.model_validate(
                {
                    "apiVersion": "initrunner/v1",
                    "kind": "Agent",
                    "metadata": {"name": "bad"},
                    "cases": [],
                }
            )

    def test_invalid_api_version_rejected(self):
        with pytest.raises(ValidationError):
            TestSuiteDefinition.model_validate(
                {
                    "apiVersion": "wrong/v99",
                    "kind": "TestSuite",
                    "metadata": {"name": "bad"},
                    "cases": [],
                }
            )

    def test_missing_metadata_rejected(self):
        with pytest.raises(ValidationError):
            TestSuiteDefinition.model_validate(
                {
                    "apiVersion": "initrunner/v1",
                    "kind": "TestSuite",
                    "cases": [],
                }
            )


class TestAssertionTypes:
    def test_contains_assertion(self):
        a = ContainsAssertion(value="hello")
        assert a.type == "contains"
        assert a.case_insensitive is False

    def test_contains_case_insensitive(self):
        a = ContainsAssertion(value="hello", case_insensitive=True)
        assert a.case_insensitive is True

    def test_not_contains_assertion(self):
        a = NotContainsAssertion(value="error")
        assert a.type == "not_contains"
        assert a.case_insensitive is False

    def test_regex_assertion(self):
        a = RegexAssertion(pattern=r"\d+")
        assert a.type == "regex"
        assert a.pattern == r"\d+"


class TestTestCase:
    def test_minimal_case(self):
        tc = TestCase(name="basic", prompt="hello")
        assert tc.expected_output is None
        assert tc.assertions == []

    def test_case_with_expected_output(self):
        tc = TestCase(name="math", prompt="2+2?", expected_output="4")
        assert tc.expected_output == "4"

    def test_case_with_assertions(self):
        tc = TestCase(
            name="test",
            prompt="hello",
            assertions=[  # type: ignore[arg-type]
                {"type": "contains", "value": "hi"},
                {"type": "regex", "pattern": r"\w+"},
            ],
        )
        assert len(tc.assertions) == 2
        assert isinstance(tc.assertions[0], ContainsAssertion)
        assert isinstance(tc.assertions[1], RegexAssertion)

    def test_invalid_assertion_type_rejected(self):
        with pytest.raises(ValidationError):
            TestCase(
                name="bad",
                prompt="hello",
                assertions=[{"type": "unknown", "value": "x"}],  # type: ignore[arg-type]
            )


class TestDiscriminatedUnion:
    def test_discriminated_union_contains(self):
        suite = TestSuiteDefinition.model_validate(
            {
                "apiVersion": "initrunner/v1",
                "kind": "TestSuite",
                "metadata": {"name": "union-test"},
                "cases": [
                    {
                        "name": "t",
                        "prompt": "p",
                        "assertions": [{"type": "contains", "value": "x"}],
                    }
                ],
            }
        )
        assert isinstance(suite.cases[0].assertions[0], ContainsAssertion)

    def test_discriminated_union_not_contains(self):
        suite = TestSuiteDefinition.model_validate(
            {
                "apiVersion": "initrunner/v1",
                "kind": "TestSuite",
                "metadata": {"name": "union-test"},
                "cases": [
                    {
                        "name": "t",
                        "prompt": "p",
                        "assertions": [{"type": "not_contains", "value": "x"}],
                    }
                ],
            }
        )
        assert isinstance(suite.cases[0].assertions[0], NotContainsAssertion)

    def test_discriminated_union_regex(self):
        suite = TestSuiteDefinition.model_validate(
            {
                "apiVersion": "initrunner/v1",
                "kind": "TestSuite",
                "metadata": {"name": "union-test"},
                "cases": [
                    {
                        "name": "t",
                        "prompt": "p",
                        "assertions": [{"type": "regex", "pattern": r"\d+"}],
                    }
                ],
            }
        )
        assert isinstance(suite.cases[0].assertions[0], RegexAssertion)
