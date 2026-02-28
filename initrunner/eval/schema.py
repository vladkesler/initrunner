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


Assertion = Annotated[
    ContainsAssertion
    | NotContainsAssertion
    | RegexAssertion
    | LLMJudgeAssertion
    | ToolCallsAssertion
    | MaxTokensAssertion
    | MaxLatencyAssertion,
    Field(discriminator="type"),
]


class TestCase(BaseModel):
    name: str
    prompt: str
    expected_output: str | None = None
    assertions: list[Assertion] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


class TestSuiteMetadata(BaseModel):
    name: str


class TestSuiteDefinition(BaseModel):
    apiVersion: ApiVersion
    kind: Literal["TestSuite"]
    metadata: TestSuiteMetadata
    cases: list[TestCase] = Field(default_factory=list)
