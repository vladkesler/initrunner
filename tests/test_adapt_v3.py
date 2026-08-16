"""v3 documents adapt onto today's Role / Team / Flow runners."""

from __future__ import annotations

from pathlib import Path

from initrunner.agent.loader import load_role
from initrunner.agent.schema.adapt import (
    document_to_flow,
    document_to_team,
    run_kind_from_mapping,
)
from initrunner.agent.schema.normalize import normalize_mapping
from initrunner.flow.loader import load_flow
from initrunner.team.loader import load_team


def test_run_kind_flat() -> None:
    assert run_kind_from_mapping({"name": "a", "prompt": "hi"}) == "Agent"
    assert (
        run_kind_from_mapping(
            {"name": "t", "agents": {"a": "one", "b": "two"}}
        )
        == "Team"
    )
    assert (
        run_kind_from_mapping(
            {
                "name": "g",
                "agents": {
                    "a": {"use": "./a.yaml", "then": {"to": "b"}},
                    "b": {"use": "./b.yaml"},
                },
            }
        )
        == "Flow"
    )


def test_load_flat_hello_world() -> None:
    role = load_role(Path("examples/roles/hello-world.yaml"))
    assert role.metadata.name == "hello-world"
    assert "friendly greeter" in role.spec.role


def test_document_to_team() -> None:
    result = normalize_mapping(
        {
            "name": "code-review",
            "model": "openai:gpt-5-mini",
            "agents": {
                "architect": "review design",
                "security": "find vulns",
            },
        }
    )
    team = document_to_team(result.document)
    assert list(team.spec.personas) == ["architect", "security"]
    assert team.spec.strategy == "sequential"
    assert team.spec.personas["architect"].role == "review design"


def test_document_to_flow_inline() -> None:
    result = normalize_mapping(
        {
            "name": "pipe",
            "agents": {
                "writer": {
                    "prompt": "write a draft",
                    "then": {"to": "editor"},
                },
                "editor": {"prompt": "edit the draft"},
            },
        }
    )
    flow = document_to_flow(result.document)
    assert flow.spec.agents["writer"].inline_role is not None
    assert flow.spec.agents["writer"].inline_role.spec.role == "write a draft"
    assert flow.spec.agents["editor"].needs == ["writer"]


def test_load_team_accepts_flat(tmp_path: Path) -> None:
    p = tmp_path / "team.yaml"
    p.write_text(
        "name: code-review\n"
        "model: openai:gpt-5-mini\n"
        "agents:\n"
        "  architect: review design\n"
        "  security: find vulns\n"
    )
    team = load_team(p)
    assert len(team.spec.personas) == 2


def test_load_flow_accepts_flat(tmp_path: Path) -> None:
    p = tmp_path / "flow.yaml"
    p.write_text(
        "name: pipe\n"
        "agents:\n"
        "  writer:\n"
        "    prompt: write\n"
        "    then:\n"
        "      to: editor\n"
        "  editor:\n"
        "    prompt: edit\n"
    )
    flow = load_flow(p)
    assert "writer" in flow.spec.agents
    assert flow.spec.agents["writer"].sink is not None
