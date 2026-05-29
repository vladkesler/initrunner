"""Reasoning tool configurations: think, clarify, todo, calculator, datetime."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from initrunner.agent.schema.tools._base import ToolConfigBase


class ThinkToolConfig(ToolConfigBase):
    type: Literal["think"] = "think"
    critique: bool = False
    max_thoughts: int = Field(default=50, ge=1, le=200)

    def summary(self) -> str:
        suffix = " (critique)" if self.critique else ""
        return f"think{suffix}"


class ClarifyToolConfig(ToolConfigBase):
    type: Literal["clarify"] = "clarify"
    max_clarifications: int = Field(default=3, ge=1, le=10)
    timeout_seconds: int = Field(default=300, ge=30, le=3600)

    def summary(self) -> str:
        return f"clarify: max={self.max_clarifications}"


class TodoToolConfig(ToolConfigBase):
    type: Literal["todo"] = "todo"
    max_items: int = Field(default=30, ge=1, le=100)
    shared: bool = False
    shared_path: str = ""

    @model_validator(mode="after")
    def _validate_shared(self) -> TodoToolConfig:
        if self.shared and not self.shared_path:
            raise ValueError("'shared_path' is required when shared is true")
        return self

    def summary(self) -> str:
        suffix = " (shared)" if self.shared else ""
        return f"todo{suffix}"


class BlackboardToolConfig(ToolConfigBase):
    """Shared-state coordination for agents inside one flow run.

    A flow agent declares ``type: blackboard`` to post, read, and claim
    structured entries on a per-run blackboard. The board lives in the flow
    graph state, so an upstream agent can post a value that a downstream
    agent (or a fan-in join) reads without threading it through prompt text.
    The tool is only active inside a flow; a standalone single-shot run has
    no blackboard and the tool is never built.
    """

    type: Literal["blackboard"] = "blackboard"
    max_entries: int = Field(default=100, ge=1, le=1000)
    max_value_chars: int = Field(default=10_000, ge=1, le=100_000)

    def summary(self) -> str:
        return f"blackboard: max_entries={self.max_entries}"


class CalculatorToolConfig(ToolConfigBase):
    type: Literal["calculator"] = "calculator"
    max_expression_length: int = 1000

    def summary(self) -> str:
        return "calculator"


class DateTimeToolConfig(ToolConfigBase):
    type: Literal["datetime"] = "datetime"
    default_timezone: str = "UTC"

    def summary(self) -> str:
        return f"datetime: {self.default_timezone}"
