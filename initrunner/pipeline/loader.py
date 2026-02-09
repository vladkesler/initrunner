"""Load and validate pipeline YAML definitions."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import ValidationError

from initrunner.pipeline.schema import PipelineDefinition


class PipelineLoadError(Exception):
    """Raised when a pipeline definition cannot be loaded or validated."""


def load_pipeline(path: Path) -> PipelineDefinition:
    """Read a YAML file and validate it as a PipelineDefinition."""
    try:
        raw = path.read_text()
    except OSError as e:
        raise PipelineLoadError(f"Cannot read {path}: {e}") from e

    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as e:
        raise PipelineLoadError(f"Invalid YAML in {path}: {e}") from e

    if not isinstance(data, dict):
        raise PipelineLoadError(f"Expected a YAML mapping in {path}, got {type(data).__name__}")

    try:
        return PipelineDefinition.model_validate(data)
    except ValidationError as e:
        raise PipelineLoadError(f"Validation failed for {path}:\n{e}") from e
