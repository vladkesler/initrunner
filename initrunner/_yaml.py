"""Shared YAML-to-Pydantic loader utility."""

from __future__ import annotations

from pathlib import Path
from typing import TypeVar

import yaml
from pydantic import BaseModel, ValidationError

_T = TypeVar("_T", bound=BaseModel)


def load_yaml_model(
    path: Path,
    model_cls: type[_T],
    error_cls: type[Exception],
) -> _T:
    """Read a YAML file and validate it against a Pydantic model.

    Parameters:
        path: Path to the YAML file.
        model_cls: The Pydantic model class to validate against.
        error_cls: The exception class to raise on any failure.

    Returns:
        A validated instance of *model_cls*.
    """
    try:
        raw = path.read_text()
    except OSError as e:
        raise error_cls(f"Cannot read {path}: {e}") from e

    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as e:
        raise error_cls(f"Invalid YAML in {path}: {e}") from e

    if not isinstance(data, dict):
        raise error_cls(f"Expected a YAML mapping in {path}, got {type(data).__name__}")

    try:
        return model_cls.model_validate(data)
    except ValidationError as e:
        raise error_cls(f"Validation failed for {path}:\n{e}") from e
