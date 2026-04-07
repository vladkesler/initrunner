"""Adapter from services flow validation to the dashboard's response schema.

The actual validation logic lives in :mod:`initrunner.services.flow_validation`
so the CLI pre-flight and the dashboard editor share a single source of truth.
This module exists only to convert service-layer ``ValidationIssue`` objects
into the API-facing ``ValidationIssueResponse`` shape.
"""

from __future__ import annotations

from initrunner.dashboard.schemas import ValidationIssueResponse
from initrunner.services.flow_validation import _validate_yaml as _validate_flow_text


def validate_flow_yaml(yaml_text: str) -> list[ValidationIssueResponse]:
    """Validate flow YAML and return dashboard-shaped issue responses."""
    _, issues = _validate_flow_text(yaml_text)
    return [
        ValidationIssueResponse(
            field=issue.field,
            message=issue.message,
            severity=issue.severity,
        )
        for issue in issues
    ]
