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
    line: int | None = None
    column: int | None = None
    suggestion: str | None = None


# Mapping from Pydantic error type strings to short fix suggestions.
# Pydantic v2 error types are a stable API; see
# https://docs.pydantic.dev/latest/errors/validation_errors/.
_PYDANTIC_TYPE_SUGGESTIONS: dict[str, str] = {
    "string_type": "expected a string; check for missing quotes or a stray number",
    "int_type": "expected an integer",
    "int_parsing": "expected an integer",
    "float_type": "expected a number",
    "bool_type": "expected a boolean (true/false)",
    "list_type": "expected a list (use - items)",
    "dict_type": "expected a mapping (key: value)",
    "missing": "this field is required; add the key",
    "extra_forbidden": "unknown field; check for typos against the schema",
    "union_tag_invalid": "the discriminator value is not one of the allowed types",
    "union_tag_not_found": "missing 'type:' key for this entry",
    "literal_error": "value must be one of the allowed literals",
}


def parse_yaml_text(text: str) -> tuple[dict | None, list[ValidationIssue]]:
    """Parse YAML text into a raw dict, collecting syntax issues.

    Returns ``(raw_dict, issues)``.  If parsing fails, ``raw_dict`` is
    ``None`` and *issues* contains the error annotated with 1-based line
    and column when PyYAML provides a ``problem_mark``.
    """
    issues: list[ValidationIssue] = []

    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as e:
        line: int | None = None
        column: int | None = None
        mark = getattr(e, "problem_mark", None)
        if mark is not None:
            # PyYAML marks are 0-based; users expect 1-based.
            line = mark.line + 1
            column = mark.column + 1
        issues.append(
            ValidationIssue(
                field="yaml",
                message=f"Invalid YAML syntax: {e}",
                severity="error",
                line=line,
                column=column,
                suggestion="check indentation, trailing colons, and quoting",
            )
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
    Populates ``suggestion`` from ``err["type"]`` for known Pydantic error
    types -- this is a stable API, not message string matching.
    """
    from pydantic import ValidationError

    if isinstance(exc, ValidationError):
        return [
            ValidationIssue(
                field=".".join(str(loc) for loc in err["loc"]),
                message=err["msg"],
                severity="error",
                suggestion=_PYDANTIC_TYPE_SUGGESTIONS.get(err.get("type", "")),
            )
            for err in exc.errors()
        ]
    return [ValidationIssue(field="spec", message=str(exc), severity="error")]


def unwrap_pydantic_error(exc: BaseException) -> list[ValidationIssue]:
    """Convert a (possibly ``ValueError``-wrapped) ``ValidationError`` to issues.

    Inspects ``__cause__`` so that the ``deprecations`` module's
    ``raise ValueError(str(exc)) from exc`` pattern still yields per-field
    issues. Falls back to a single generic issue when no Pydantic error is
    available.
    """
    from pydantic import ValidationError

    if isinstance(exc, ValidationError):
        return extract_pydantic_errors(exc)
    cause = exc.__cause__
    if isinstance(cause, ValidationError):
        return extract_pydantic_errors(cause)
    return [ValidationIssue(field="schema", message=str(exc), severity="error")]
