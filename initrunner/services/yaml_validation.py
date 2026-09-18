"""Single CLI-facing entry point for YAML pre-flight validation.

``validate_yaml_file`` detects the YAML kind, dispatches to the right
service-layer validator, and recurses into role files referenced by a
flow.  It is the only function the CLI needs to call before running an
agent, team, or flow.

The typed replacement classifier is
``initrunner.agent.schema.document.classify_yaml_file`` (unknown/broken
input is ``invalid``, not Agent). It is not wired into
``detect_yaml_kind`` while ``FLAT_SCHEMA_LOADER_ENABLED`` is false — do
not accept flat-agent documents here until ``run`` can execute them.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

from initrunner.services._yaml_validation import ValidationIssue, extract_pydantic_errors


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

    from initrunner.agent.schema.adapt import run_kind_from_mapping
    from initrunner.agent.schema.document import DocumentClass, classify_mapping

    classification = classify_mapping(data)
    if classification.document_class is DocumentClass.REMOVED_COMPOSE:
        raise InvalidComposeKindError(
            "kind: Compose has been renamed to kind: Flow. "
            "Also rename spec.services to spec.agents and depends_on to needs. "
            "See docs/orchestration/flow.md"
        )
    if classification.document_class is DocumentClass.FLAT_AGENT:
        return run_kind_from_mapping(data)
    if classification.legacy_kind in {"Agent", "Team", "Flow", "Service", "TestSuite"}:
        return classification.legacy_kind
    kind = data.get("kind", "Agent")
    return kind


def validate_yaml_file(
    path: Path,
) -> tuple[Any | None, str, list[ValidationIssue]]:
    """Detect kind, validate, return ``(definition, kind, issues)``.

    Every agent file a document references (``use:`` in a flat file, ``role:``
    in an envelope flow) is validated too, and its issues come back with an
    ``agents.<name>.`` prefix so the user can tell which file is broken.
    """
    return _validate_file(path, frozenset())


def _validate_file(
    path: Path, visiting: frozenset[Path]
) -> tuple[Any | None, str, list[ValidationIssue]]:
    """``validate_yaml_file`` with the chain of files that led here, to stop cycles."""
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

    from initrunner.agent.schema.document import DocumentClass, classify_yaml_text

    visiting = visiting | {path.resolve()}
    if classify_yaml_text(text).document_class is DocumentClass.FLAT_AGENT:
        defn, issues = _validate_flat_document(text, path, visiting)
        return defn, kind, issues

    if kind == "Team":
        from initrunner.services.team_builder import validate_team_yaml

        defn, issues = validate_team_yaml(text)
    elif kind == "Flow":
        from initrunner.services.flow_validation import _validate_yaml as _validate_flow_text

        defn, issues = _validate_flow_text(text)
        if defn is not None:
            references = {
                name: cfg.role for name, cfg in defn.spec.agents.items() if cfg.inline_role is None
            }
            issues.extend(_reference_issues(references, path.parent, visiting))
    else:
        from initrunner.services.agent_builder import _validate_yaml as _validate_role_text

        defn, issues = _validate_role_text(text)

    return defn, kind, issues


def _validate_flat_document(
    text: str, path: Path, visiting: frozenset[Path]
) -> tuple[Any | None, list[ValidationIssue]]:
    """Check the document, then each file it references, then compose them.

    The composing step (``adapt_mapping``) loads referenced files and stops at
    the first bad one with a single message, so the document's own schema and
    every ``use:`` file are checked first: each problem gets its own issue,
    with a path into the file it is in.
    """
    import yaml
    from pydantic import ValidationError

    from initrunner.agent.schema.adapt import adapt_mapping
    from initrunner.agent.schema.normalize import normalize_mapping

    data = yaml.safe_load(text)
    issues: list[ValidationIssue] = []
    try:
        normalize_mapping(data)
    except ValidationError as exc:
        issues.extend(extract_pydantic_errors(exc))
    except Exception as exc:
        issues.append(ValidationIssue(field="document", message=str(exc), severity="error"))

    agents = data.get("agents")
    if isinstance(agents, dict):
        references = {
            name: child["use"]
            for name, child in agents.items()
            if isinstance(child, dict) and isinstance(child.get("use"), str)
        }
        issues.extend(_reference_issues(references, path.parent, visiting))

    if any(issue.severity == "error" for issue in issues):
        return None, issues

    try:
        _legacy, defn, _ir = adapt_mapping(data, base_dir=path.parent, source_path=path.resolve())
    except Exception as exc:
        issues.append(ValidationIssue(field="document", message=str(exc), severity="error"))
        return None, issues
    return defn, issues


def _reference_issues(
    references: dict[str, str], base_dir: Path, visiting: frozenset[Path]
) -> list[ValidationIssue]:
    """Validate each referenced agent file, prefixing its issues with ``agents.<name>.``."""
    issues: list[ValidationIssue] = []
    for name, use in references.items():
        field = f"agents.{name}.use"
        ref = (base_dir / use).resolve()
        if ref in visiting:
            issues.append(
                ValidationIssue(
                    field=field,
                    message=f"{use} leads back to a file that references it",
                    severity="error",
                    suggestion="point this at an agent file, not at the file that uses it",
                )
            )
            continue
        if not ref.exists():
            issues.append(
                ValidationIssue(
                    field=field,
                    message=f"Role file not found: {ref}",
                    severity="error",
                    suggestion="check the path is relative to this file's directory",
                )
            )
            continue
        _, member_kind, sub_issues = _validate_file(ref, visiting)
        if member_kind != "Agent":
            issues.append(
                ValidationIssue(
                    field=field,
                    message=f"{use} is a {member_kind}, not a single agent",
                    severity="error",
                    suggestion="point this at a single agent file",
                )
            )
        issues.extend(_prefix_issues(sub_issues, f"agents.{name}."))
    return issues


def _prefix_issues(issues: list[ValidationIssue], prefix: str) -> list[ValidationIssue]:
    """Return *issues* with ``prefix`` prepended to each ``field``."""
    return [replace(issue, field=f"{prefix}{issue.field}") for issue in issues]
