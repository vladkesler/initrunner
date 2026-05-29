"""Pydantic models for test suite YAML definitions."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field

from initrunner.agent.schema.base import ApiVersion


class TestSuiteKind:
    TEST_SUITE = "TestSuite"


class ContainsAssertion(BaseModel):
    type: Literal["contains"] = "contains"
    value: str
    case_insensitive: bool = False


class NotContainsAssertion(BaseModel):
    type: Literal["not_contains"] = "not_contains"
    value: str
    case_insensitive: bool = False


class RegexAssertion(BaseModel):
    type: Literal["regex"] = "regex"
    pattern: str


class LLMJudgeAssertion(BaseModel):
    type: Literal["llm_judge"] = "llm_judge"
    criteria: list[str]
    model: str = "openai:gpt-4o-mini"


class ToolCallsAssertion(BaseModel):
    type: Literal["tool_calls"] = "tool_calls"
    expected: list[str]
    mode: Literal["exact", "subset", "superset"] = "subset"


class MaxTokensAssertion(BaseModel):
    type: Literal["max_tokens"] = "max_tokens"
    limit: int


class MaxLatencyAssertion(BaseModel):
    type: Literal["max_latency"] = "max_latency"
    limit_ms: int


class ToolOrderAssertion(BaseModel):
    """Assert that tools were called in a given relative order.

    Reads the structured run-event timeline (``RunResult.event_timeline``) so it
    can distinguish call sequence, not just call presence. ``sequence`` lists the
    expected tool names; with ``strict=False`` (the default) the names must appear
    in this relative order allowing other calls in between, and with
    ``strict=True`` the observed tool-call sequence must equal ``sequence``
    exactly.
    """

    type: Literal["tool_order"] = "tool_order"
    sequence: list[str]
    strict: bool = False


class ReasoningBudgetAssertion(BaseModel):
    """Assert the agent stayed within a reasoning-token budget.

    Reads ``RunResult.reasoning_tokens`` (the thinking-token count surfaced by
    item 3). A run that reports zero reasoning tokens is treated as within any
    budget, so this assertion never penalizes models that do not emit thinking.
    """

    type: Literal["reasoning_budget"] = "reasoning_budget"
    max_reasoning_tokens: int


class MemoryConsultedAssertion(BaseModel):
    """Assert the agent did (or did not) consult memory during the run.

    Looks for memory tool calls in the run-event timeline. ``tools`` overrides
    the default set of names treated as memory consultation. Set
    ``expected=False`` to assert that memory was *not* touched.
    """

    type: Literal["memory_consulted"] = "memory_consulted"
    expected: bool = True
    tools: list[str] = Field(
        default_factory=lambda: ["recall_memory", "search_memory", "memory_search"]
    )


class SpanAssertion(BaseModel):
    """Assert on the OTel span tree and run-event timeline.

    ``name_contains`` matches against both span names and timeline entry tool
    names; ``attribute`` / ``attribute_value`` match span attributes. When
    ``count`` is set the number of matching spans must equal it exactly,
    otherwise at least one match is required. Evaluation falls back to the
    run-event timeline when no OTel provider recorded spans, so span assertions
    work without Logfire or an OTLP backend configured.
    """

    type: Literal["span"] = "span"
    name_contains: str | None = None
    attribute: str | None = None
    attribute_value: str | None = None
    count: int | None = None


Assertion = Annotated[
    ContainsAssertion
    | NotContainsAssertion
    | RegexAssertion
    | LLMJudgeAssertion
    | ToolCallsAssertion
    | MaxTokensAssertion
    | MaxLatencyAssertion
    | ToolOrderAssertion
    | ReasoningBudgetAssertion
    | MemoryConsultedAssertion
    | SpanAssertion,
    Field(discriminator="type"),
]


class TestCase(BaseModel):
    __test__ = False

    name: str
    prompt: str
    expected_output: str | None = None
    assertions: list[Assertion] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


class TestSuiteMetadata(BaseModel):
    name: str


class TestSuiteDefinition(BaseModel):
    __test__ = False

    apiVersion: ApiVersion
    kind: Literal["TestSuite"]
    metadata: TestSuiteMetadata
    cases: list[TestCase] = Field(default_factory=list)
