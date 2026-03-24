"""Load and validate compose YAML definitions."""

from __future__ import annotations

from pathlib import Path


class ComposeLoadError(Exception):
    """Raised when a compose definition cannot be loaded or validated."""


def load_compose(path: Path):  # -> ComposeDefinition
    """Read a YAML file and validate it as a ComposeDefinition."""
    from initrunner._yaml import load_raw_yaml
    from initrunner.deprecations import validate_compose_dict

    raw = load_raw_yaml(path, ComposeLoadError)
    try:
        compose, _hits = validate_compose_dict(raw)
    except (ValueError, Exception) as e:
        raise ComposeLoadError(f"Validation failed for {path}:\n{e}") from e
    return compose
