"""Shared flow YAML validation logic used by CLI pre-flight and dashboard editor."""

from __future__ import annotations

from typing import TYPE_CHECKING

from initrunner.services._yaml_validation import (
    ValidationIssue,
    parse_yaml_text,
    unwrap_pydantic_error,
)

if TYPE_CHECKING:
    from initrunner.flow.schema import FlowDefinition


def _validate_yaml(text: str) -> tuple[FlowDefinition | None, list[ValidationIssue]]:
    """Parse and validate flow YAML, returning the definition and any issues.

    Schema-only -- does not check that referenced role files exist on disk
    or recursively validate them.  The CLI's ``validate_yaml_file`` does
    that step on top of this function.
    """
    raw, issues = parse_yaml_text(text)
    if raw is None:
        return None, issues

    from initrunner.agent.schema.adapt import document_to_flow
    from initrunner.agent.schema.document import DocumentClass, classify_mapping
    from initrunner.agent.schema.normalize import normalize_mapping
    from initrunner.deprecations import validate_flow_dict

    try:
        if classify_mapping(raw).document_class is DocumentClass.FLAT_AGENT:
            flow = document_to_flow(normalize_mapping(raw).document)
        else:
            flow, _hits = validate_flow_dict(raw)
    except Exception as exc:
        issues.extend(unwrap_pydantic_error(exc))
        return None, issues

    return flow, issues
