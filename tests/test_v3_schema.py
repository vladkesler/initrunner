"""Flat AgentDocument: shorthand, extra=forbid, composition contract."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from initrunner.agent.schema.v3 import AgentDocument, parse_v3_tool_list


def test_solo_minimal() -> None:
    doc = AgentDocument.model_validate(
        {
            "name": "hello-world",
            "model": "openai:gpt-5-mini",
            "prompt": "You are a friendly greeter.",
        }
    )
    assert doc.prompt is not None
    assert doc.model is not None
    assert doc.model.provider == "openai"
    assert doc.model.name == "gpt-5-mini"
    assert doc.agents is None


def test_solo_requires_prompt() -> None:
    with pytest.raises(ValidationError, match="prompt"):
        AgentDocument.model_validate({"name": "hello-world", "model": "openai:gpt-5-mini"})


def test_unknown_top_level_key_forbidden() -> None:
    with pytest.raises(ValidationError, match="personas"):
        AgentDocument.model_validate(
            {
                "name": "hello-world",
                "prompt": "hi",
                "personas": {"a": "x", "b": "y"},
            }
        )


def test_tool_shorthand_and_unknown_key() -> None:
    tools = parse_v3_tool_list(
        [
            "search",
            {"filesystem": {"root_path": ".", "read_only": True}},
        ]
    )
    assert tools[0].type == "search"
    assert tools[1].type == "filesystem"
    assert tools[1].root_path == "."

    with pytest.raises(ValueError, match="Unknown keys"):
        parse_v3_tool_list([{"filesystem": {"root": ".", "read_only": True}}])


def test_preset_team_defaults_sequential() -> None:
    doc = AgentDocument.model_validate(
        {
            "name": "code-review",
            "model": "openai:gpt-5-mini",
            "agents": {
                "architect": "review design",
                "security": "find vulns",
            },
        }
    )
    assert doc.run == "sequential"
    assert doc.prompt is None
    assert doc.agents is not None
    assert doc.agents["architect"].prompt == "review design"


def test_prompt_forbidden_when_composed() -> None:
    with pytest.raises(ValidationError, match="prompt"):
        AgentDocument.model_validate(
            {
                "name": "code-review",
                "prompt": "coordinate",
                "agents": {"a": "one", "b": "two"},
            }
        )


def test_run_and_then_are_mutually_exclusive() -> None:
    with pytest.raises(ValidationError, match="not both"):
        AgentDocument.model_validate(
            {
                "name": "support-desk",
                "run": "sequential",
                "agents": {
                    "intake": {
                        "use": "./intake.yaml",
                        "then": {"to": "writer"},
                    },
                    "writer": {"use": "./writer.yaml"},
                },
            }
        )


def test_graph_then_unknown_target() -> None:
    with pytest.raises(ValidationError, match="unknown"):
        AgentDocument.model_validate(
            {
                "name": "support-desk",
                "agents": {
                    "intake": {
                        "use": "./intake.yaml",
                        "then": {"to": "missing"},
                    },
                },
            }
        )


def test_one_child_allowed() -> None:
    doc = AgentDocument.model_validate(
        {
            "name": "single-child",
            "agents": {"only": {"use": "./only.yaml"}},
        }
    )
    assert doc.run == "sequential"
    assert doc.agents is not None
    assert len(doc.agents) == 1


def test_spec_version_must_be_three() -> None:
    with pytest.raises(ValidationError, match="spec_version"):
        AgentDocument.model_validate({"name": "hello-world", "prompt": "hi", "spec_version": 2})


def test_team_budgets_solo_rejected() -> None:
    with pytest.raises(ValidationError, match="team_token_budget"):
        AgentDocument.model_validate(
            {
                "name": "hello-world",
                "prompt": "hi",
                "guardrails": {"team_token_budget": 1000},
            }
        )


def test_child_environment_not_allowed_on_graph() -> None:
    with pytest.raises(ValidationError, match="environment"):
        AgentDocument.model_validate(
            {
                "name": "desk",
                "agents": {
                    "intake": {
                        "use": "./a.yaml",
                        "environment": {"X": "1"},
                        "then": {"to": "out"},
                    },
                    "out": {"use": "./b.yaml"},
                },
            }
        )
