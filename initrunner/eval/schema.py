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


Assertion = Annotated[
    ContainsAssertion | NotContainsAssertion | RegexAssertion,
    Field(discriminator="type"),
]


class TestCase(BaseModel):
    name: str
    prompt: str
    expected_output: str | None = None
    assertions: list[Assertion] = []


class TestSuiteMetadata(BaseModel):
    name: str


class TestSuiteDefinition(BaseModel):
    apiVersion: ApiVersion
    kind: Literal["TestSuite"]
    metadata: TestSuiteMetadata
    cases: list[TestCase] = []
