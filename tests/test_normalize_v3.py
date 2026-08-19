"""Envelope → v3 document + IR. Equivalence of old vs rewritten flat YAML."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from initrunner.agent.schema.document import DocumentClass
from initrunner.agent.schema.normalize import (
    INERT_FLOW_CHILD_FIELDS,
    NormalizeError,
    normalize_mapping,
)


def test_normalize_envelope_agent() -> None:
    result = normalize_mapping(
        {
            "apiVersion": "initrunner/v1",
            "kind": "Agent",
            "metadata": {"name": "hello-world", "description": "greet"},
            "spec": {
                "role": "You are a friendly greeter.",
                "model": {"provider": "openai", "name": "gpt-5-mini"},
            },
        }
    )
    assert result.classification.document_class is DocumentClass.ENVELOPE_AGENT
    assert result.document.prompt == "You are a friendly greeter."
    assert result.ir.shape == "solo"
    assert result.ir.handoff is None
    assert result.document.spec_version is None


def test_normalize_envelope_team_personas() -> None:
    result = normalize_mapping(
        {
            "apiVersion": "initrunner/v1",
            "kind": "Team",
            "metadata": {"name": "code-review-team"},
            "spec": {
                "model": {"provider": "openai", "name": "gpt-5-mini"},
                "personas": {
                    "architect": "review design",
                    "security": {
                        "role": "find vulns",
                        "tools_mode": "replace",
                    },
                },
                "strategy": "sequential",
            },
        }
    )
    assert result.classification.document_class is DocumentClass.ENVELOPE_TEAM
    assert result.ir.shape == "preset"
    assert result.ir.handoff == "team"
    assert result.ir.run == "sequential"
    assert result.document.agents is not None
    assert result.document.agents["architect"].prompt == "review design"
    assert result.document.agents["security"].tools_mode == "replace"
    names = [c.name for c in result.ir.children]
    assert names == ["architect", "security"]


def test_group_normalizes_to_roster() -> None:
    """Reference-only compositions hand off to nothing, so they are not presets."""
    result = normalize_mapping(
        {
            "name": "desk",
            "agents": {
                "intake": {"use": "roles/intake.yaml"},
                "writer": {"use": "roles/writer.yaml"},
            },
        }
    )
    assert result.ir.shape == "roster"
    assert result.ir.handoff is None
    assert result.ir.run is None
    assert [c.use for c in result.ir.children] == ["roles/intake.yaml", "roles/writer.yaml"]


def test_normalize_envelope_flow_then_and_needs() -> None:
    result = normalize_mapping(
        {
            "apiVersion": "initrunner/v1",
            "kind": "Flow",
            "metadata": {"name": "support-desk"},
            "spec": {
                "agents": {
                    "intake": {
                        "role": "roles/intake.yaml",
                        "sink": {"type": "delegate", "target": "writer", "strategy": "all"},
                    },
                    "writer": {
                        "role": "roles/writer.yaml",
                        "needs": ["intake"],
                        "restart": {"condition": "on-failure", "max_retries": 3},
                    },
                }
            },
        }
    )
    assert result.ir.shape == "graph"
    assert result.ir.handoff == "flow"
    children = {c.name: c for c in result.ir.children}
    assert children["intake"].use == "roles/intake.yaml"
    assert children["intake"].then is not None
    assert children["intake"].then.to == ("writer",)
    assert children["writer"].needs == ("intake",)
    assert result.document.agents is not None
    assert result.document.agents["writer"].after == ["intake"]
    assert any("restart" in w for w in result.warnings)
    assert "restart" in INERT_FLOW_CHILD_FIELDS


def test_service_and_invalid_rejected() -> None:
    try:
        normalize_mapping({"kind": "Service", "metadata": {"name": "x"}, "spec": {}})
    except NormalizeError as exc:
        assert "Service" in str(exc)
    else:
        raise AssertionError("expected NormalizeError")

    try:
        normalize_mapping({"foo": "bar"})
    except NormalizeError:
        pass
    else:
        raise AssertionError("expected NormalizeError")


def test_bundled_examples_normalize() -> None:
    root = Path(__file__).resolve().parents[1]
    samples = [
        root / "examples/roles/hello-world.yaml",
        root / "examples/teams/code-review.yaml",
        root / "examples/flows/support-desk/flow.yaml",
    ]
    for path in samples:
        result = normalize_mapping(yaml.safe_load(path.read_text()))
        assert result.document.name
        assert result.ir.name


def test_equivalence_team_envelope_and_flat() -> None:
    from initrunner.agent.schema.adapt import adapt_mapping
    from initrunner.agent.schema.render import render_document
    from initrunner.services.migrate import runner_models_equivalent

    envelope = {
        "apiVersion": "initrunner/v1",
        "kind": "Team",
        "metadata": {"name": "code-review-team"},
        "spec": {
            "model": {"provider": "openai", "name": "gpt-5-mini"},
            "personas": {
                "architect": "review design",
                "security": "find vulns",
            },
        },
    }
    first = normalize_mapping(envelope)
    text = render_document(first.document)
    rendered = yaml.safe_load(text)
    second = normalize_mapping(rendered)
    assert first.ir.shape == second.ir.shape
    assert first.ir.run == second.ir.run
    assert [c.name for c in first.ir.children] == [c.name for c in second.ir.children]
    assert [c.prompt for c in first.ir.children] == [c.prompt for c in second.ir.children]
    assert first.ir.handoff == second.ir.handoff
    _, old_model, _ = adapt_mapping(envelope)
    _, new_model, _ = adapt_mapping(rendered)
    assert runner_models_equivalent(old_model, new_model)


def test_non_kebab_flow_name_is_rejected() -> None:
    with pytest.raises(NormalizeError, match="kebab-case"):
        normalize_mapping(
            {
                "apiVersion": "initrunner/v1",
                "kind": "Flow",
                "metadata": {"name": "Support Desk"},
                "spec": {"agents": {"intake": {"role": "roles/intake.yaml"}}},
            }
        )
