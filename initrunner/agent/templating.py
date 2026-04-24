"""Minimal ``{{variable}}`` template renderer for role prompts.

Scope is deliberately narrow (v1): a flat-scalar JSON Schema declares the
allowed variable names and their types, and ``render`` substitutes matching
values from a dict at run time.  Anything beyond flat scalars (nested
objects, arrays, ``$ref``, ``oneOf``, etc.) is rejected at schema-validation
time so users never silently get a half-resolved prompt.

This intentionally avoids ``pydantic-handlebars`` and the
``pydantic-ai-slim[spec]`` extra -- that dependency only pays off when we
want to route every agent through ``Agent.from_spec()``, which we don't.
"""

from __future__ import annotations

import re
from typing import Any

_VAR_RE = re.compile(r"\{\{\s*(\w+)\s*\}\}")

_SCALAR_JSON_TYPES = {"string", "integer", "number", "boolean"}


class TemplatingError(Exception):
    """Raised for schema-shape violations and undeclared variable references."""


def has_templates(text: str) -> bool:
    """Return True when *text* contains at least one ``{{var}}`` placeholder."""
    return bool(_VAR_RE.search(text or ""))


def extract_vars(text: str) -> set[str]:
    """Return the set of variable names referenced in *text*."""
    return {m.group(1) for m in _VAR_RE.finditer(text or "")}


def _require_flat_scalar_schema(schema: dict[str, Any]) -> None:
    """Enforce the v1 subset: ``{type: object, properties: {k: {type: scalar}}}``."""
    if schema.get("type") != "object":
        raise TemplatingError(
            f"deps_schema must be {{'type': 'object', ...}}; got type={schema.get('type')!r}"
        )
    for key in ("$ref", "oneOf", "anyOf", "allOf", "patternProperties", "additionalProperties"):
        if key in schema:
            raise TemplatingError(
                f"deps_schema uses unsupported keyword '{key}'. "
                f"v1 accepts only a flat object with scalar properties."
            )

    properties = schema.get("properties") or {}
    if not isinstance(properties, dict):
        raise TemplatingError("deps_schema.properties must be a mapping")
    for name, prop in properties.items():
        if not isinstance(prop, dict):
            raise TemplatingError(f"deps_schema.properties[{name!r}] must be a mapping")
        prop_type = prop.get("type")
        if prop_type not in _SCALAR_JSON_TYPES:
            raise TemplatingError(
                f"deps_schema.properties[{name!r}].type must be one of "
                f"{sorted(_SCALAR_JSON_TYPES)}; got {prop_type!r}. "
                f"v1 does not support nested objects or arrays."
            )


def validate_schema_and_template(template: str, schema: dict[str, Any]) -> None:
    """Validate the schema shape and that every ``{{var}}`` is declared in it.

    Raises ``TemplatingError`` on any violation.  Safe to call at role-load
    time before any runtime values exist.
    """
    _require_flat_scalar_schema(schema)
    declared = set((schema.get("properties") or {}).keys())
    used = extract_vars(template)
    undeclared = used - declared
    if undeclared:
        raise TemplatingError(
            f"Template references undeclared variables {sorted(undeclared)}. "
            f"Add them to deps_schema.properties or remove the placeholders."
        )


def _coerce(value: Any, prop_type: str, name: str) -> str:
    """Render a single scalar into its string form for substitution."""
    if prop_type == "boolean":
        return "true" if bool(value) else "false"
    if prop_type in {"integer", "number"}:
        try:
            return str(int(value)) if prop_type == "integer" else str(float(value))
        except (TypeError, ValueError) as exc:
            raise TemplatingError(
                f"Value for {{{{{name}}}}} is not a valid {prop_type}: {value!r}"
            ) from exc
    return str(value)


def render(template: str, schema: dict[str, Any], values: dict[str, Any]) -> str:
    """Substitute ``{{var}}`` occurrences in *template* using *values*.

    Required keys (per ``schema['required']``) must be present in *values* or
    a ``TemplatingError`` is raised.  Extra keys in *values* are ignored.
    """
    properties = schema.get("properties") or {}
    required = set(schema.get("required") or [])

    missing = [k for k in required if k not in values or values[k] is None]
    if missing:
        raise TemplatingError(
            f"Missing required template values: {sorted(missing)}. Pass them via --var KEY=VALUE."
        )

    def _sub(match: re.Match[str]) -> str:
        name = match.group(1)
        prop = properties.get(name, {})
        if name not in values:
            return match.group(0)  # undeclared-optional: leave the placeholder as-is
        return _coerce(values[name], prop.get("type", "string"), name)

    return _VAR_RE.sub(_sub, template)
