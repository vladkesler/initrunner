"""Load and validate team YAML definitions."""

from __future__ import annotations

from pathlib import Path

from initrunner._yaml import load_yaml_model
from initrunner.team.schema import TeamDefinition


class TeamLoadError(Exception):
    """Raised when a team definition cannot be loaded or validated."""


def load_team(path: Path) -> TeamDefinition:
    """Read a YAML file and validate it as a TeamDefinition."""
    return load_yaml_model(path, TeamDefinition, TeamLoadError)
