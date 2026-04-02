"""Reasoning configuration for agent execution patterns."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator


class ReflexionDimension(BaseModel):
    """A single evaluation dimension for a reflexion round."""

    name: str = Field(min_length=1)
    prompt: str = Field(min_length=1)


DEFAULT_REFLEXION_DIMENSIONS: list[ReflexionDimension] = [
    ReflexionDimension(
        name="correctness",
        prompt=(
            "Check for factual errors, logical flaws, or incorrect assumptions. "
            "Do code examples compile and produce correct output? "
            "Are all claims verifiable? Fix any errors you find."
        ),
    ),
    ReflexionDimension(
        name="completeness",
        prompt=(
            "Are there missing sections, unaddressed requirements, or gaps in coverage? "
            "Is enough context provided for the reader? "
            "Are error conditions and edge cases handled? Fill in any gaps."
        ),
    ),
    ReflexionDimension(
        name="clarity",
        prompt=(
            "Is the structure logical and easy to follow? "
            "Are explanations concise without being ambiguous? "
            "Are concrete examples provided where they would help? "
            "Simplify or restructure anything confusing."
        ),
    ),
]


class ReasoningConfig(BaseModel):
    """Controls how the execution layer orchestrates agent reasoning."""

    pattern: Literal["react", "todo_driven", "plan_execute", "reflexion"] = "react"
    auto_plan: bool = False
    reflection_rounds: int = Field(default=0, ge=0, le=3)
    reflection_dimensions: list[ReflexionDimension] | None = None
    auto_detect: bool = True

    @model_validator(mode="after")
    def _resolve_dimensions(self) -> ReasoningConfig:
        dims = self.reflection_dimensions
        if dims is not None:
            if len(dims) == 0:
                raise ValueError("reflection_dimensions must be non-empty when provided")
            if len(dims) > 3:
                raise ValueError("Maximum 3 reflection dimensions allowed")
            if self.reflection_rounds == 0:
                self.reflection_rounds = len(dims)
        return self
