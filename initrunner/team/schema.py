"""Pydantic models for team YAML definitions."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from initrunner.agent.schema.base import ApiVersion, Metadata, ModelConfig
from initrunner.agent.schema.role import parse_tool_list
from initrunner.agent.schema.tools import ToolConfig


class TeamGuardrails(BaseModel):
    """Per-persona guardrails plus cumulative team-level budgets."""

    # Per-persona (passed to each execute_run via Guardrails)
    max_tokens_per_run: Annotated[int, Field(gt=0)] = 50000
    max_tool_calls: Annotated[int, Field(ge=0)] = 20
    timeout_seconds: Annotated[int, Field(gt=0)] = 300

    # Cumulative team-level budgets
    team_token_budget: Annotated[int, Field(gt=0)] | None = None
    team_timeout_seconds: Annotated[int, Field(gt=0)] | None = None


class TeamSpec(BaseModel):
    model: ModelConfig
    personas: dict[str, str] = Field(min_length=2)
    tools: list[ToolConfig] = []
    guardrails: TeamGuardrails = TeamGuardrails()
    handoff_max_chars: Annotated[int, Field(gt=0)] = 4000

    @field_validator("tools", mode="before")
    @classmethod
    def _parse_tools(cls, v: Any) -> list:
        return parse_tool_list(v)

    @model_validator(mode="after")
    def _validate_persona_names(self) -> TeamSpec:
        import re

        pattern = re.compile(r"^[a-z0-9][a-z0-9-]*[a-z0-9]$")
        for name in self.personas:
            if not pattern.match(name):
                raise ValueError(
                    f"Invalid persona name '{name}': "
                    f"must match ^[a-z0-9][a-z0-9-]*[a-z0-9]$ "
                    f"(lowercase, hyphens, no leading/trailing hyphens)"
                )
        return self


class TeamDefinition(BaseModel):
    apiVersion: ApiVersion
    kind: Literal["Team"]
    metadata: Metadata
    spec: TeamSpec
