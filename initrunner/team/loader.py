"""Load and validate team YAML definitions."""

from __future__ import annotations

from pathlib import Path


class TeamLoadError(Exception):
    """Raised when a team definition cannot be loaded or validated."""


def load_team(path: Path):  # -> TeamDefinition
    """Read a YAML file and validate it as a TeamDefinition."""
    from initrunner._yaml import load_raw_yaml
    from initrunner.deprecations import validate_team_dict

    raw = load_raw_yaml(path, TeamLoadError)
    try:
        team, _hits = validate_team_dict(raw)
    except (ValueError, Exception) as e:
        raise TeamLoadError(f"Validation failed for {path}:\n{e}") from e
    return team
