"""Single CLI-facing entry point for YAML pre-flight validation.

``validate_yaml_file`` detects the YAML kind, dispatches to the right
service-layer validator, and recurses into role files referenced by a
flow.  It is the only function the CLI needs to call before running an
agent, team, or flow.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

from initrunner.services._yaml_validation import ValidationIssue


class InvalidComposeKindError(Exception):
    """Raised when a YAML file uses the removed ``kind: Compose`` schema."""


def detect_yaml_kind(path: Path) -> str:
    """Peek at a YAML file's ``kind`` field without full validation.

    Returns the kind string (e.g. ``"Agent"``, ``"Team"``, ``"Flow"``).
    Defaults to ``"Agent"`` on any failure.

    Raises :class:`InvalidComposeKindError` if the file uses the removed
    ``kind: Compose`` -- the CLI converts this into a Rich-formatted exit.
    """
    import yaml

    try:
        with open(path) as f:
            data = yaml.safe_load(f)
    except Exception:
        return "Agent"

    if not isinstance(data, dict):
        return "Agent"

    kind = data.get("kind", "Agent")
    if kind == "Compose":
        raise InvalidComposeKindError(
            "kind: Compose has been renamed to kind: Flow. "
            "Also rename spec.services to spec.agents and depends_on to needs. "
            "See docs/orchestration/flow.md"
        )
    return kind


def validate_yaml_file(
    path: Path,
) -> tuple[Any | None, str, list[ValidationIssue]]:
    """Detect kind, validate, return ``(definition, kind, issues)``.

    For Flow files, recurses into each referenced role file and prefixes
    nested issue field paths with ``agents.<name>.`` so the user can tell
    which referenced file is broken.
    """
    kind = detect_yaml_kind(path)

    try:
        text = path.read_text()
    except OSError as e:
        return (
            None,
            kind,
            [
                ValidationIssue(
                    field="file",
                    message=f"Cannot read {path}: {e}",
                    severity="error",
                )
            ],
        )

    if kind == "Team":
        from initrunner.services.team_builder import validate_team_yaml

        defn, issues = validate_team_yaml(text)
    elif kind == "Flow":
        from initrunner.services.flow_validation import _validate_yaml as _validate_flow_text

        defn, issues = _validate_flow_text(text)
        if defn is not None:
            base_dir = path.parent
            for agent_name, cfg in defn.spec.agents.items():
                role_path = base_dir / cfg.role
                if not role_path.exists():
                    issues.append(
                        ValidationIssue(
                            field=f"spec.agents.{agent_name}.role",
                            message=f"Role file not found: {role_path}",
                            severity="error",
                            suggestion="check the path is relative to the flow file directory",
                        )
                    )
                    continue
                _, _, sub_issues = validate_yaml_file(role_path)
                issues.extend(_prefix_issues(sub_issues, f"agents.{agent_name}."))
    else:
        from initrunner.services.agent_builder import _validate_yaml as _validate_role_text

        defn, issues = _validate_role_text(text)

    return defn, kind, issues


def _prefix_issues(issues: list[ValidationIssue], prefix: str) -> list[ValidationIssue]:
    """Return *issues* with ``prefix`` prepended to each ``field``."""
    return [replace(issue, field=f"{prefix}{issue.field}") for issue in issues]
