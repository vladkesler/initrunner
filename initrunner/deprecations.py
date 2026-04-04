"""Centralized deprecation registry for role, flow, and team YAML schemas."""

from __future__ import annotations

import copy
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Literal

CURRENT_ROLE_SPEC_VERSION: int = 2

REMOVED_FIELD_MESSAGE_MAX_MEMORIES: str = (
    "memory.max_memories has been removed. "
    "Use memory.semantic.max_memories instead:\n"
    "  memory:\n"
    "    semantic:\n"
    "      max_memories: <value>"
)

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------


class SchemaKind(StrEnum):
    ROLE = "role"
    FLOW = "Flow"
    COMPOSE = "Compose"  # kept for detection of old compose files
    TEAM = "team"


_SENTINEL = object()


@dataclass(frozen=True)
class DeprecationRule:
    id: str
    kind: frozenset[SchemaKind]
    field_path: str
    since: int | None  # spec_version when deprecated; None for non-role kinds
    severity: Literal["warning", "error"]
    message: str
    match_value: Any = field(default=_SENTINEL)  # _SENTINEL = any value triggers
    migrate: Callable[[dict, str], None] | None = None


@dataclass
class DeprecationHit:
    id: str
    field_path: str
    severity: Literal["warning", "error"]
    message: str
    original_value: Any
    auto_fixed: bool


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------

_RULES: list[DeprecationRule] = [
    DeprecationRule(
        id="DEP001",
        kind=frozenset({SchemaKind.ROLE}),
        field_path="spec.memory.max_memories",
        since=2,
        severity="error",
        message=REMOVED_FIELD_MESSAGE_MAX_MEMORIES,
    ),
    DeprecationRule(
        id="DEP002",
        kind=frozenset({SchemaKind.ROLE}),
        field_path="spec.ingest.store_backend",
        since=2,
        severity="error",
        message="store_backend 'zvec' has been removed. Use 'lancedb' instead.",
        match_value="zvec",
    ),
    DeprecationRule(
        id="DEP003",
        kind=frozenset({SchemaKind.ROLE}),
        field_path="spec.memory.store_backend",
        since=2,
        severity="error",
        message="store_backend 'zvec' has been removed. Use 'lancedb' instead.",
        match_value="zvec",
    ),
    DeprecationRule(
        id="DEP004",
        kind=frozenset({SchemaKind.FLOW, SchemaKind.TEAM}),
        field_path="spec.shared_memory.store_backend",
        since=None,
        severity="error",
        message="store_backend 'zvec' has been removed. Use 'lancedb' instead.",
        match_value="zvec",
    ),
    DeprecationRule(
        id="DEP005",
        kind=frozenset({SchemaKind.FLOW, SchemaKind.TEAM}),
        field_path="spec.shared_documents.store_backend",
        since=None,
        severity="error",
        message="store_backend 'zvec' has been removed. Use 'lancedb' instead.",
        match_value="zvec",
    ),
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_nested(data: dict, dot_path: str) -> tuple[bool, Any]:
    """Probe a nested dict by dot-separated path. Returns (found, value)."""
    cursor: Any = data
    for key in dot_path.split("."):
        if not isinstance(cursor, dict) or key not in cursor:
            return False, None
        cursor = cursor[key]
    return True, cursor


# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------


def apply_deprecations(data: dict, kind: SchemaKind) -> tuple[dict, list[DeprecationHit]]:
    """Walk deprecation rules for *kind*, returning (migrated_data, hits).

    Deep-copies *data* before any mutation.  Does **not** raise.
    """
    out = copy.deepcopy(data)
    hits: list[DeprecationHit] = []

    for rule in _RULES:
        if kind not in rule.kind:
            continue
        found, value = _get_nested(out, rule.field_path)
        if not found:
            continue
        if rule.match_value is not _SENTINEL and value != rule.match_value:
            continue

        if rule.migrate is not None:
            rule.migrate(out, rule.field_path)
            hits.append(
                DeprecationHit(
                    id=rule.id,
                    field_path=rule.field_path,
                    severity=rule.severity,
                    message=rule.message,
                    original_value=value,
                    auto_fixed=True,
                )
            )
        else:
            hits.append(
                DeprecationHit(
                    id=rule.id,
                    field_path=rule.field_path,
                    severity=rule.severity,
                    message=rule.message,
                    original_value=value,
                    auto_fixed=False,
                )
            )

    return out, hits


# ---------------------------------------------------------------------------
# Shared validators
# ---------------------------------------------------------------------------


def validate_role_dict(
    raw: dict,
) -> tuple[Any, list[DeprecationHit]]:  # Any = RoleDefinition (lazy)
    """Apply deprecations, reject errors, validate schema. Returns (role, hits).

    Raises ``ValueError`` on future spec_version, error-severity hits, or
    schema validation failure.
    """
    from pydantic import ValidationError

    sv = raw.get("metadata", {}).get("spec_version", 1) if isinstance(raw, dict) else 1
    if sv > CURRENT_ROLE_SPEC_VERSION:
        raise ValueError(
            f"spec_version {sv} is newer than the supported version "
            f"({CURRENT_ROLE_SPEC_VERSION}). Please upgrade initrunner."
        )

    migrated, hits = apply_deprecations(raw, SchemaKind.ROLE)

    errors = [h for h in hits if h.severity == "error"]
    if errors:
        msgs = "\n".join(f"  {h.id}: {h.message}" for h in errors)
        raise ValueError(f"Deprecated fields:\n{msgs}")

    from initrunner.agent.schema.role import RoleDefinition

    try:
        role = RoleDefinition.model_validate(migrated)
    except ValidationError as exc:
        raise ValueError(str(exc)) from exc

    return role, hits


def _check_compose_hard_break(raw: dict) -> None:
    """Raise if *raw* uses the removed ``kind: Compose`` schema.

    Detects ``kind: Compose``, ``spec.services``, and ``depends_on`` inside
    agent configs and gives a clear migration message.
    """
    hints: list[str] = []

    if raw.get("kind") == "Compose":
        hints.append("kind: Compose -> kind: Flow")

    spec = raw.get("spec")
    if isinstance(spec, dict) and "services" in spec:
        hints.append("spec.services -> spec.agents")
        # Check for depends_on inside service configs
        services = spec["services"]
        if isinstance(services, dict):
            for _name, svc in services.items():
                if isinstance(svc, dict) and "depends_on" in svc:
                    hints.append("depends_on -> needs (inside each agent config)")
                    break

    if hints:
        renames = "; ".join(hints)
        raise ValueError(
            f"kind: Compose has been renamed to kind: Flow. "
            f"Rename the following fields: {renames}. "
            f"See docs/orchestration/flow.md"
        )


def validate_flow_dict(
    raw: dict,
) -> tuple[Any, list[DeprecationHit]]:  # Any = FlowDefinition (lazy)
    """Apply deprecations, reject errors, validate flow schema.

    Also detects the removed ``kind: Compose`` format and raises a clear
    migration error.
    """
    from pydantic import ValidationError

    # Hard-break: reject old compose format with actionable message
    _check_compose_hard_break(raw)

    migrated, hits = apply_deprecations(raw, SchemaKind.FLOW)

    errors = [h for h in hits if h.severity == "error"]
    if errors:
        msgs = "\n".join(f"  {h.id}: {h.message}" for h in errors)
        raise ValueError(f"Deprecated fields:\n{msgs}")

    from initrunner.flow.schema import FlowDefinition

    try:
        flow = FlowDefinition.model_validate(migrated)
    except ValidationError as exc:
        raise ValueError(str(exc)) from exc

    return flow, hits


# Backward-compatible alias (used by dashboard until Phase 5)
validate_compose_dict = validate_flow_dict


def validate_team_dict(
    raw: dict,
) -> tuple[Any, list[DeprecationHit]]:  # Any = TeamDefinition (lazy)
    """Apply deprecations, reject errors, validate team schema."""
    from pydantic import ValidationError

    migrated, hits = apply_deprecations(raw, SchemaKind.TEAM)

    errors = [h for h in hits if h.severity == "error"]
    if errors:
        msgs = "\n".join(f"  {h.id}: {h.message}" for h in errors)
        raise ValueError(f"Deprecated fields:\n{msgs}")

    from initrunner.team.schema import TeamDefinition

    try:
        team = TeamDefinition.model_validate(migrated)
    except ValidationError as exc:
        raise ValueError(str(exc)) from exc

    return team, hits


# ---------------------------------------------------------------------------
# Inspection (for doctor, non-raising)
# ---------------------------------------------------------------------------


@dataclass
class RoleInspection:
    spec_version: int
    current_version: int
    hits: list[DeprecationHit]
    schema_error: str | None
    role: Any | None  # RoleDefinition | None


def inspect_role_data(raw: dict) -> RoleInspection:
    """Non-raising role inspection for ``doctor --role``.

    Only raises on future spec_version (unrecoverable).
    """
    sv = raw.get("metadata", {}).get("spec_version", 1) if isinstance(raw, dict) else 1
    if sv > CURRENT_ROLE_SPEC_VERSION:
        raise ValueError(
            f"spec_version {sv} is newer than the supported version "
            f"({CURRENT_ROLE_SPEC_VERSION}). Please upgrade initrunner."
        )

    migrated, hits = apply_deprecations(raw, SchemaKind.ROLE)

    schema_error: str | None = None
    role = None
    try:
        from initrunner.agent.schema.role import RoleDefinition

        role = RoleDefinition.model_validate(migrated)
    except Exception as exc:
        schema_error = str(exc)

    return RoleInspection(
        spec_version=sv,
        current_version=CURRENT_ROLE_SPEC_VERSION,
        hits=hits,
        schema_error=schema_error,
        role=role,
    )
