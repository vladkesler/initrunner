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


def test_one_bare_reference_is_a_group() -> None:
    """A lone `use:` reference is a group of one, not a one-persona preset.

    Grouping is uniform at any size, so adding a second member later does not
    change how the first one is addressed.
    """
    doc = AgentDocument.model_validate(
        {
            "name": "single-child",
            "agents": {"only": {"use": "./only.yaml"}},
        }
    )
    assert doc.run is None
    assert doc.agents is not None
    assert len(doc.agents) == 1


def test_one_inline_child_still_gets_a_preset() -> None:
    doc = AgentDocument.model_validate(
        {
            "name": "single-child",
            "agents": {"only": {"prompt": "do the thing"}},
        }
    )
    assert doc.run == "sequential"


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


@pytest.mark.parametrize(
    "override",
    [
        {"triggers": []},
        {"guardrails": {"max_tool_calls": 2}},
    ],
)
def test_per_child_runtime_policy_rejected_on_preset_team(override: dict) -> None:
    with pytest.raises(ValidationError, match="not supported by preset teams"):
        AgentDocument.model_validate(
            {
                "name": "review-team",
                "agents": {
                    "reviewer": {"prompt": "review", **override},
                    "writer": "write",
                },
            }
        )


# ---------------------------------------------------------------------------
# Grouped agents: reference-only compositions with no orchestration
# ---------------------------------------------------------------------------


def _group(**extra) -> dict:
    return {
        "name": "desk",
        "agents": {"intake": {"use": "roles/intake.yaml"}, "writer": {"use": "roles/writer.yaml"}},
        **extra,
    }


def test_group_keeps_no_run_preset() -> None:
    doc = AgentDocument.model_validate(_group())
    assert doc.run is None
    assert doc.agents is not None
    assert list(doc.agents) == ["intake", "writer"]


def test_group_allows_shared_stores_and_metadata() -> None:
    doc = AgentDocument.model_validate(
        _group(
            description="the desk",
            tags=["ops"],
            shared_memory={"enabled": True},
            security={"server": {"max_conversations": 10}},
        )
    )
    assert doc.shared_memory.enabled is True
    assert doc.security.server.max_conversations == 10


@pytest.mark.parametrize(
    "field,value",
    [
        ("model", "openai:gpt-5-mini"),
        ("tools", ["calculator"]),
        ("triggers", [{"type": "cron", "schedule": "0 * * * *", "prompt": "tick"}]),
        ("sinks", [{"type": "file", "path": "/tmp/out.txt"}]),
        ("skills", ["./skills/foo"]),
        ("memory", {"store_path": "/tmp/m.db"}),
        ("durability", {"enabled": True}),
        ("handoff_max_chars", 100),
    ],
)
def test_group_rejects_behaviour_fields(field: str, value: object) -> None:
    with pytest.raises(ValidationError, match="cannot be set on a group"):
        AgentDocument.model_validate(_group(**{field: value}))


def test_group_rejects_non_listener_security() -> None:
    with pytest.raises(ValidationError, match="security"):
        AgentDocument.model_validate(_group(security={"content": {"pii_redaction": True}}))


def test_group_allows_rate_limit_and_server() -> None:
    doc = AgentDocument.model_validate(
        _group(
            security={"server": {"require_https": True}, "rate_limit": {"requests_per_minute": 30}}
        )
    )
    assert doc.security.server.require_https is True
    assert doc.security.rate_limit.requests_per_minute == 30


def test_mixed_bare_reference_and_inline_child_is_rejected() -> None:
    with pytest.raises(ValidationError, match="neither a team nor a group"):
        AgentDocument.model_validate(
            {
                "name": "desk",
                "agents": {
                    "intake": {"use": "roles/intake.yaml"},
                    "writer": {"prompt": "write it up"},
                },
            }
        )


def test_mixed_children_accepted_once_run_is_explicit() -> None:
    doc = AgentDocument.model_validate(
        {
            "name": "desk",
            "run": "sequential",
            "agents": {
                "intake": {"use": "roles/intake.yaml"},
                "writer": {"prompt": "write it up"},
            },
        }
    )
    assert doc.run == "sequential"


def test_referenced_children_with_overrides_stay_a_preset() -> None:
    """Overrides make a member a persona, so the old preset behaviour stands."""
    doc = AgentDocument.model_validate(
        {
            "name": "desk",
            "agents": {
                "intake": {"use": "roles/intake.yaml", "prompt": "triage"},
                "writer": {"use": "roles/writer.yaml", "model": "openai:gpt-5-mini"},
            },
        }
    )
    assert doc.run == "sequential"


def test_run_with_one_agent_is_rejected() -> None:
    with pytest.raises(ValidationError, match="at least two agents"):
        AgentDocument.model_validate(
            {"name": "desk", "run": "parallel", "agents": {"only": {"use": "roles/only.yaml"}}}
        )
