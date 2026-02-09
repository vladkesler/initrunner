"""Pydantic models for pipeline YAML definitions."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator


class PipelineStep(BaseModel):
    name: str
    role_file: str | None = None
    url: str | None = None
    mode: Literal["inline", "mcp"] = "inline"
    prompt: str
    depends_on: list[str] = []
    timeout_seconds: int = 300
    retry_count: int = 0
    output_format: Literal["text", "json"] = "text"
    condition: str | None = None
    headers_env: dict[str, str] = {}


class PipelineMetadata(BaseModel):
    name: str
    description: str = ""


class PipelineSpec(BaseModel):
    steps: list[PipelineStep] = Field(min_length=1)
    error_strategy: Literal["fail-fast", "continue"] = "fail-fast"
    max_parallel: int = 4

    @model_validator(mode="after")
    def _validate_dag(self) -> PipelineSpec:
        step_names = {s.name for s in self.steps}

        # Check unique names
        if len(step_names) != len(self.steps):
            seen: set[str] = set()
            for s in self.steps:
                if s.name in seen:
                    raise ValueError(f"Duplicate step name: '{s.name}'")
                seen.add(s.name)

        # Check depends_on references exist
        for step in self.steps:
            for dep in step.depends_on:
                if dep not in step_names:
                    raise ValueError(f"Step '{step.name}' depends on unknown step '{dep}'")

        # Check mode constraints
        for step in self.steps:
            if step.mode == "inline" and not step.role_file:
                raise ValueError(f"Inline step '{step.name}' requires 'role_file'")
            if step.mode == "mcp" and not step.url:
                raise ValueError(f"MCP step '{step.name}' requires 'url'")

        # Cycle detection via topological sort (Kahn's algorithm)
        from initrunner._graph import CycleError, detect_cycle

        edges = {step.name: list(step.depends_on) for step in self.steps}
        try:
            detect_cycle(step_names, edges, "dependency")
        except CycleError:
            raise ValueError("Pipeline contains a dependency cycle") from None

        return self


class PipelineDefinition(BaseModel):
    apiVersion: str
    kind: Literal["Pipeline"]
    metadata: PipelineMetadata
    spec: PipelineSpec
