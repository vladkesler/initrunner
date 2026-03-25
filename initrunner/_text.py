"""Shared text utilities."""

from __future__ import annotations

from typing import Any


def safe_substitute(template: str, values: dict[str, Any]) -> str:
    """Replace ``{key}`` placeholders using str.replace -- no format string injection."""
    result = template
    for k, v in values.items():
        result = result.replace(f"{{{k}}}", str(v))
    return result
