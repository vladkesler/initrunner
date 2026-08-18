"""Typed YAML document classifier. Invalid input is not an Agent."""

from __future__ import annotations

from pathlib import Path

import yaml

from initrunner.agent.schema.document import (
    DocumentClass,
    assert_loader_may_accept,
    classify_mapping,
    classify_yaml_file,
    classify_yaml_text,
)


def test_envelope_kinds() -> None:
    assert classify_mapping({"kind": "Agent"}).document_class is DocumentClass.ENVELOPE_AGENT
    assert classify_mapping({"kind": "Team"}).document_class is DocumentClass.ENVELOPE_TEAM
    assert classify_mapping({"kind": "Flow"}).document_class is DocumentClass.ENVELOPE_FLOW
    assert classify_mapping({"kind": "Service"}).document_class is DocumentClass.SERVICE
    assert classify_mapping({"kind": "TestSuite"}).document_class is DocumentClass.TEST_SUITE


def test_removed_compose() -> None:
    assert classify_mapping({"kind": "Compose"}).document_class is DocumentClass.REMOVED_COMPOSE
    assert (
        classify_mapping({"spec": {"services": {}}}).document_class is DocumentClass.REMOVED_COMPOSE
    )


def test_removed_pipeline_is_invalid() -> None:
    result = classify_mapping({"kind": "Pipeline"})
    assert result.document_class is DocumentClass.INVALID
    assert result.legacy_kind is None


def test_unknown_kind_is_invalid() -> None:
    result = classify_mapping({"kind": "Wizard"})
    assert result.document_class is DocumentClass.INVALID


def test_parse_error_is_invalid_not_agent() -> None:
    result = classify_yaml_text(": : :")
    assert result.document_class is DocumentClass.INVALID
    assert "invalid YAML" in result.reason


def test_non_mapping_is_invalid() -> None:
    assert classify_mapping(["not", "a", "map"]).document_class is DocumentClass.INVALID
    assert classify_yaml_text("- just a list\n").document_class is DocumentClass.INVALID


def test_unreadable_file_is_invalid(tmp_path: Path) -> None:
    missing = tmp_path / "nope.yaml"
    result = classify_yaml_file(missing)
    assert result.document_class is DocumentClass.INVALID
    assert "cannot read" in result.reason


def test_flat_agent() -> None:
    result = classify_mapping(
        {"name": "hello-world", "prompt": "You greet people.", "model": "openai:gpt-5-mini"}
    )
    assert result.document_class is DocumentClass.FLAT_AGENT
    assert result.legacy_kind == "Agent"


def test_envelope_without_kind_is_invalid() -> None:
    result = classify_mapping(
        {"apiVersion": "initrunner/v1", "metadata": {"name": "x"}, "spec": {"role": "hi"}}
    )
    assert result.document_class is DocumentClass.INVALID


def test_bare_on_is_boolean_key() -> None:
    """Why the public field stays `triggers`, not `on`."""
    loaded = yaml.safe_load("on:\n  - webhook\n")
    assert True in loaded
    assert "on" not in loaded


def test_flat_loader_enabled() -> None:
    classification = classify_mapping({"name": "hello-world", "prompt": "hi"})
    assert classification.document_class is DocumentClass.FLAT_AGENT
    assert_loader_may_accept(classification)
