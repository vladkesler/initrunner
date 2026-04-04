"""Shared flow YAML validation logic used by both builder and editor."""

from __future__ import annotations

import yaml

from initrunner.dashboard.schemas import ValidationIssueResponse


def validate_flow_yaml(yaml_text: str) -> list[ValidationIssueResponse]:
    """Parse and validate flow YAML against schema + graph rules only."""
    from initrunner.deprecations import validate_compose_dict

    issues: list[ValidationIssueResponse] = []
    try:
        raw = yaml.safe_load(yaml_text)
    except yaml.YAMLError as exc:
        issues.append(ValidationIssueResponse(field="yaml", message=str(exc), severity="error"))
        return issues

    if not isinstance(raw, dict):
        issues.append(
            ValidationIssueResponse(
                field="yaml",
                message="Expected a YAML mapping",
                severity="error",
            )
        )
        return issues

    spec_raw = raw.get("spec")
    if not isinstance(spec_raw, dict):
        issues.append(
            ValidationIssueResponse(
                field="spec",
                message="Missing 'spec' section",
                severity="error",
            )
        )
        return issues

    try:
        validate_compose_dict(raw)
    except ValueError as ve:
        issues.append(
            ValidationIssueResponse(field="deprecation", message=str(ve), severity="error")
        )
    except Exception as ve:
        if hasattr(ve, "errors"):
            error_list = ve.errors()  # type: ignore[union-attr]
        else:
            error_list = [{"msg": str(ve), "loc": ("spec",)}]
        for err in error_list:
            loc = ".".join(str(part) for part in err.get("loc", []))
            issues.append(
                ValidationIssueResponse(
                    field=loc or "spec",
                    message=str(err.get("msg", str(err))),
                    severity="error",
                )
            )

    return issues
