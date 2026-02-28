"""Tests for eval suite YAML schema parsing and validation."""

import pytest
from pydantic import ValidationError

from initrunner.eval.schema import (
    ContainsAssertion,
    LLMJudgeAssertion,
    MaxLatencyAssertion,
    MaxTokensAssertion,
    NotContainsAssertion,
    RegexAssertion,
    TestCase,
    TestSuiteDefinition,
    ToolCallsAssertion,
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

    def test_cases_default_factory(self):
        """Verify cases uses Field(default_factory=list)."""
        s1 = TestSuiteDefinition.model_validate(
            {"apiVersion": "initrunner/v1", "kind": "TestSuite", "metadata": {"name": "a"}}
        )
        s2 = TestSuiteDefinition.model_validate(
            {"apiVersion": "initrunner/v1", "kind": "TestSuite", "metadata": {"name": "b"}}
        )
        assert s1.cases is not s2.cases


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

    def test_llm_judge_assertion(self):
        a = LLMJudgeAssertion(criteria=["Is helpful", "Is accurate"])
        assert a.type == "llm_judge"
        assert a.model == "openai:gpt-4o-mini"
        assert len(a.criteria) == 2

    def test_llm_judge_custom_model(self):
        a = LLMJudgeAssertion(criteria=["test"], model="anthropic:claude-sonnet-4-6")
        assert a.model == "anthropic:claude-sonnet-4-6"

    def test_tool_calls_assertion(self):
        a = ToolCallsAssertion(expected=["web_search", "file_read"])
        assert a.type == "tool_calls"
        assert a.mode == "subset"
        assert a.expected == ["web_search", "file_read"]

    def test_tool_calls_exact_mode(self):
        a = ToolCallsAssertion(expected=["search"], mode="exact")
        assert a.mode == "exact"

    def test_tool_calls_superset_mode(self):
        a = ToolCallsAssertion(expected=["a", "b"], mode="superset")
        assert a.mode == "superset"

    def test_max_tokens_assertion(self):
        a = MaxTokensAssertion(limit=2000)
        assert a.type == "max_tokens"
        assert a.limit == 2000

    def test_max_latency_assertion(self):
        a = MaxLatencyAssertion(limit_ms=5000)
        assert a.type == "max_latency"
        assert a.limit_ms == 5000


class TestTestCase:
    def test_minimal_case(self):
        tc = TestCase(name="basic", prompt="hello")
        assert tc.expected_output is None
        assert tc.assertions == []
        assert tc.tags == []

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

    def test_case_with_tags(self):
        tc = TestCase(name="tagged", prompt="hello", tags=["search", "fast"])
        assert tc.tags == ["search", "fast"]

    def test_tags_default_factory(self):
        """Verify tags uses Field(default_factory=list)."""
        tc1 = TestCase(name="a", prompt="p")
        tc2 = TestCase(name="b", prompt="p")
        assert tc1.tags is not tc2.tags

    def test_assertions_default_factory(self):
        """Verify assertions uses Field(default_factory=list)."""
        tc1 = TestCase(name="a", prompt="p")
        tc2 = TestCase(name="b", prompt="p")
        assert tc1.assertions is not tc2.assertions

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

    def test_discriminated_union_llm_judge(self):
        suite = TestSuiteDefinition.model_validate(
            {
                "apiVersion": "initrunner/v1",
                "kind": "TestSuite",
                "metadata": {"name": "union-test"},
                "cases": [
                    {
                        "name": "t",
                        "prompt": "p",
                        "assertions": [
                            {"type": "llm_judge", "criteria": ["is good"]},
                        ],
                    }
                ],
            }
        )
        assert isinstance(suite.cases[0].assertions[0], LLMJudgeAssertion)

    def test_discriminated_union_tool_calls(self):
        suite = TestSuiteDefinition.model_validate(
            {
                "apiVersion": "initrunner/v1",
                "kind": "TestSuite",
                "metadata": {"name": "union-test"},
                "cases": [
                    {
                        "name": "t",
                        "prompt": "p",
                        "assertions": [
                            {"type": "tool_calls", "expected": ["search"]},
                        ],
                    }
                ],
            }
        )
        assert isinstance(suite.cases[0].assertions[0], ToolCallsAssertion)

    def test_discriminated_union_max_tokens(self):
        suite = TestSuiteDefinition.model_validate(
            {
                "apiVersion": "initrunner/v1",
                "kind": "TestSuite",
                "metadata": {"name": "union-test"},
                "cases": [
                    {
                        "name": "t",
                        "prompt": "p",
                        "assertions": [
                            {"type": "max_tokens", "limit": 1000},
                        ],
                    }
                ],
            }
        )
        assert isinstance(suite.cases[0].assertions[0], MaxTokensAssertion)

    def test_discriminated_union_max_latency(self):
        suite = TestSuiteDefinition.model_validate(
            {
                "apiVersion": "initrunner/v1",
                "kind": "TestSuite",
                "metadata": {"name": "union-test"},
                "cases": [
                    {
                        "name": "t",
                        "prompt": "p",
                        "assertions": [
                            {"type": "max_latency", "limit_ms": 5000},
                        ],
                    }
                ],
            }
        )
        assert isinstance(suite.cases[0].assertions[0], MaxLatencyAssertion)

    def test_round_trip_all_types(self):
        """Verify all assertion types survive model_validate → model_dump round-trip."""
        data = {
            "apiVersion": "initrunner/v1",
            "kind": "TestSuite",
            "metadata": {"name": "round-trip"},
            "cases": [
                {
                    "name": "all",
                    "prompt": "p",
                    "tags": ["a", "b"],
                    "assertions": [
                        {"type": "contains", "value": "x"},
                        {"type": "not_contains", "value": "y"},
                        {"type": "regex", "pattern": "z"},
                        {"type": "llm_judge", "criteria": ["c1"]},
                        {"type": "tool_calls", "expected": ["t1"], "mode": "exact"},
                        {"type": "max_tokens", "limit": 100},
                        {"type": "max_latency", "limit_ms": 500},
                    ],
                }
            ],
        }
        suite = TestSuiteDefinition.model_validate(data)
        dumped = suite.model_dump()
        restored = TestSuiteDefinition.model_validate(dumped)
        assert len(restored.cases[0].assertions) == 7
        assert restored.cases[0].tags == ["a", "b"]
