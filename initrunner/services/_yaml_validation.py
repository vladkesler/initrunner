"""Shared YAML parsing and validation helpers for builder services."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import yaml


@dataclass
class ValidationIssue:
    """A single validation problem found in a YAML document."""

    field: str
    message: str
    severity: Literal["error", "warning", "info"]


def parse_yaml_text(text: str) -> tuple[dict | None, list[ValidationIssue]]:
    """Parse YAML text into a raw dict, collecting syntax issues.

    Returns ``(raw_dict, issues)``.  If parsing fails, ``raw_dict`` is
    ``None`` and *issues* contains the error.
    """
    issues: list[ValidationIssue] = []

    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as e:
        issues.append(
            ValidationIssue(field="yaml", message=f"Invalid YAML syntax: {e}", severity="error")
        )
        return None, issues

    if not isinstance(raw, dict):
        issues.append(
            ValidationIssue(field="yaml", message="YAML must be a mapping", severity="error")
        )
        return None, issues

    return raw, issues


def extract_pydantic_errors(exc: Exception) -> list[ValidationIssue]:
    """Convert a Pydantic ``ValidationError`` into ``ValidationIssue`` items.

    Falls back to a generic issue if *exc* is not a ``ValidationError``.
    """
    from pydantic import ValidationError

    if isinstance(exc, ValidationError):
        return [
            ValidationIssue(
                field=".".join(str(loc) for loc in err["loc"]),
                message=err["msg"],
                severity="error",
            )
            for err in exc.errors()
        ]
    return [ValidationIssue(field="spec", message=str(exc), severity="error")]
