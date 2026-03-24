"""Load and validate pipeline YAML definitions."""

from __future__ import annotations

from pathlib import Path

from pydantic import ValidationError

from initrunner._yaml import load_raw_yaml
from initrunner.pipeline.schema import PipelineDefinition


class PipelineLoadError(Exception):
    """Raised when a pipeline definition cannot be loaded or validated."""


def load_pipeline(path: Path) -> PipelineDefinition:
    """Read a YAML file and validate it as a PipelineDefinition."""
    data = load_raw_yaml(path, PipelineLoadError)
    try:
        return PipelineDefinition.model_validate(data)
    except ValidationError as e:
        raise PipelineLoadError(f"Validation failed for {path}:\n{e}") from e
