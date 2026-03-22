"""Reasoning configuration for agent execution patterns."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ReasoningConfig(BaseModel):
    """Controls how the execution layer orchestrates agent reasoning."""

    pattern: Literal["react", "todo_driven", "plan_execute", "reflexion"] = "react"
    auto_plan: bool = False
    reflection_rounds: int = Field(default=0, ge=0, le=3)
    auto_detect: bool = True
