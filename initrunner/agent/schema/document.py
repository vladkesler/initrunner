"""Typed classifier for InitRunner YAML documents.

``detect_yaml_kind`` still defaults parse failures to ``"Agent"``. This module
is the replacement: unknown or unreadable input is ``invalid``, not an agent.
Loaders must not accept ``flat-agent`` until ``FLAT_SCHEMA_LOADER_ENABLED`` is
on and composed documents can actually run.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, cast

import yaml

# Envelope CRD format (apiVersion/kind/metadata/spec). Independent of
# metadata.spec_version (currently 2) and the flat schema integer (3).
ENVELOPE_FORMAT = "initrunner/v1"
FLAT_SCHEMA_VERSION = 3

# Flat agent.yaml is accepted by load_role / load_team / load_flow.
FLAT_SCHEMA_LOADER_ENABLED = True

_FLAT_MARKERS = frozenset({"prompt", "agents", "model", "tools"})
_UNKNOWN_REMOVED_KINDS = frozenset({"Pipeline"})


class DocumentClass(StrEnum):
    FLAT_AGENT = "flat-agent"
    ENVELOPE_AGENT = "envelope-agent"
    ENVELOPE_TEAM = "envelope-team"
    ENVELOPE_FLOW = "envelope-flow"
    SERVICE = "service"
    TEST_SUITE = "test-suite"
    REMOVED_COMPOSE = "removed-compose"
    INVALID = "invalid"


class FlatSchemaDisabledError(Exception):
    """Raised when a flat-agent file is seen while the v3 loader is gated off."""


@dataclass(frozen=True)
class Classification:
    document_class: DocumentClass
    reason: str

    @property
    def legacy_kind(self) -> str | None:
        """Kind string the current CLI understands, or None if it should not run."""
        return {
            DocumentClass.FLAT_AGENT: "Agent",
            DocumentClass.ENVELOPE_AGENT: "Agent",
            DocumentClass.ENVELOPE_TEAM: "Team",
            DocumentClass.ENVELOPE_FLOW: "Flow",
            DocumentClass.SERVICE: "Service",
            DocumentClass.TEST_SUITE: "TestSuite",
            DocumentClass.REMOVED_COMPOSE: "Compose",
            DocumentClass.INVALID: None,
        }[self.document_class]


def classify_mapping(data: object) -> Classification:
    """Classify an already-parsed YAML value."""
    if not isinstance(data, dict):
        return Classification(
            DocumentClass.INVALID,
            f"expected a YAML mapping, got {type(data).__name__}",
        )

    mapping = cast(dict[str, Any], data)
    kind = mapping.get("kind")
    spec = mapping.get("spec")

    if kind == "Compose" or (
        isinstance(spec, dict) and "services" in spec and kind in (None, "Compose")
    ):
        return Classification(
            DocumentClass.REMOVED_COMPOSE,
            "kind: Compose has been renamed to kind: Flow",
        )
    if kind == "Service":
        return Classification(DocumentClass.SERVICE, "kind: Service")
    if kind == "TestSuite":
        return Classification(DocumentClass.TEST_SUITE, "kind: TestSuite")
    if kind == "Team":
        return Classification(DocumentClass.ENVELOPE_TEAM, "kind: Team")
    if kind == "Flow":
        return Classification(DocumentClass.ENVELOPE_FLOW, "kind: Flow")
    if kind == "Agent":
        return Classification(DocumentClass.ENVELOPE_AGENT, "kind: Agent")
    if kind in _UNKNOWN_REMOVED_KINDS:
        return Classification(
            DocumentClass.INVALID,
            f"kind: {kind} has been removed",
        )
    if kind is not None:
        return Classification(DocumentClass.INVALID, f"unknown kind: {kind!r}")

    if mapping.get("apiVersion") or "spec" in mapping or "metadata" in mapping:
        return Classification(
            DocumentClass.INVALID,
            "envelope fields present without a recognized kind",
        )

    name = mapping.get("name")
    if isinstance(name, str) and name and _FLAT_MARKERS.intersection(mapping):
        return Classification(DocumentClass.FLAT_AGENT, "flat agent document")

    return Classification(DocumentClass.INVALID, "not a recognized InitRunner document")


def classify_yaml_text(text: str) -> Classification:
    """Parse YAML text and classify it. Parse errors are invalid, not Agent."""
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        return Classification(DocumentClass.INVALID, f"invalid YAML: {exc}")
    return classify_mapping(data)


def classify_yaml_file(path: Path) -> Classification:
    """Read a file and classify it. IO/parse errors are invalid, not Agent."""
    try:
        text = path.read_text()
    except OSError as exc:
        return Classification(DocumentClass.INVALID, f"cannot read {path}: {exc}")
    return classify_yaml_text(text)


def assert_loader_may_accept(classification: Classification) -> None:
    """Refuse flat-agent documents while the v3 loader is feature-gated."""
    if classification.document_class is DocumentClass.FLAT_AGENT and not FLAT_SCHEMA_LOADER_ENABLED:
        raise FlatSchemaDisabledError(
            "flat agent.yaml (spec_version 3) is not enabled yet. "
            "Keep using the apiVersion/kind envelope, or wait for the v3 run path."
        )
