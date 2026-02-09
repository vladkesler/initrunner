"""Load and validate compose YAML definitions."""

from __future__ import annotations

from pathlib import Path

from initrunner._yaml import load_yaml_model
from initrunner.compose.schema import ComposeDefinition


class ComposeLoadError(Exception):
    """Raised when a compose definition cannot be loaded or validated."""


def load_compose(path: Path) -> ComposeDefinition:
    """Read a YAML file and validate it as a ComposeDefinition."""
    return load_yaml_model(path, ComposeDefinition, ComposeLoadError)
