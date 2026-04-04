"""Load and validate flow YAML definitions."""

from __future__ import annotations

from pathlib import Path


class FlowLoadError(Exception):
    """Raised when a flow definition cannot be loaded or validated."""


def load_flow(path: Path):  # -> FlowDefinition
    """Read a YAML file and validate it as a FlowDefinition."""
    from initrunner._yaml import load_raw_yaml
    from initrunner.deprecations import validate_flow_dict

    raw = load_raw_yaml(path, FlowLoadError)
    try:
        flow, _hits = validate_flow_dict(raw)
    except (ValueError, Exception) as e:
        raise FlowLoadError(f"Validation failed for {path}:\n{e}") from e
    return flow
