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
    success_criteria: list[str] | None = None
    """Criteria the reflexion judge verifies after each round. When set, an
    LLM-as-judge gates the self-critique loop: a round that passes every
    criterion is marked verified and the loop advances or finishes early.
    Auto-derived from ``reflection_dimensions`` names when left unset."""
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
            if self.success_criteria is None:
                self.success_criteria = [d.name for d in dims]

        if self.success_criteria is not None:
            if len(self.success_criteria) == 0:
                raise ValueError("success_criteria must be non-empty when provided")
            if len(self.success_criteria) > 10:
                raise ValueError("Maximum 10 success criteria allowed")
        return self
