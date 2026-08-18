"""Load and validate team YAML definitions."""

from __future__ import annotations

from pathlib import Path


class TeamLoadError(Exception):
    """Raised when a team definition cannot be loaded or validated."""


def load_team(path: Path):  # -> TeamDefinition
    """Read a YAML file and validate it as a TeamDefinition.

    Accepts ``kind: Team`` envelopes and flat v3 documents with ``agents``.
    """
    from initrunner._yaml import load_raw_yaml
    from initrunner.agent.schema.adapt import AdaptError, document_to_team, run_kind_from_mapping
    from initrunner.agent.schema.document import DocumentClass, classify_mapping
    from initrunner.agent.schema.normalize import NormalizeError, normalize_mapping
    from initrunner.deprecations import validate_team_dict

    raw = load_raw_yaml(path, TeamLoadError)
    try:
        if classify_mapping(raw).document_class is DocumentClass.FLAT_AGENT:
            if run_kind_from_mapping(raw) != "Team":
                raise TeamLoadError(f"{path} is not a multi-agent preset")
            return document_to_team(normalize_mapping(raw).document, base_dir=path.parent)
        team, _hits = validate_team_dict(raw)
    except (AdaptError, NormalizeError, ValueError, Exception) as e:
        raise TeamLoadError(f"Validation failed for {path}:\n{e}") from e
    return team
