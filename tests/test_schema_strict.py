"""Every config model reachable from an agent file rejects unknown keys.

A typo in a nested section used to validate clean and silently do nothing
(``memory: {retenion_days: 30}``). These tests pin the whole tree to
``extra="forbid"`` so a new model cannot quietly reopen the gap, and check
the places that must stay open: free-form mappings and skill frontmatter.
"""

from __future__ import annotations

import inspect
import typing
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from initrunner.agent.schema.normalize import normalize_mapping
from initrunner.agent.schema.role import RequiresConfig, RoleDefinition, SkillFrontmatter
from initrunner.agent.schema.tools import PluginToolConfig
from initrunner.agent.schema.v3 import AgentDocument
from initrunner.agent.tools._registry import get_tool_types
from initrunner.flow.schema import FlowDefinition
from initrunner.team.schema import TeamDefinition


def _reachable_models() -> set[type[BaseModel]]:
    """Models an agent file can configure: flat and envelope trees, every tool,
    and a skill's ``requires`` block."""
    seen: set[type[BaseModel]] = set()

    def walk(annotation: Any) -> None:
        if typing.get_origin(annotation) is not None:
            for arg in typing.get_args(annotation):
                walk(arg)
            return
        if not (inspect.isclass(annotation) and issubclass(annotation, BaseModel)):
            return
        if annotation in seen:
            return
        seen.add(annotation)
        for field in annotation.model_fields.values():
            walk(field.annotation)

    for root in (AgentDocument, RoleDefinition, TeamDefinition, FlowDefinition, RequiresConfig):
        walk(root)
    for config_class in get_tool_types().values():
        walk(config_class)
    return seen


def test_every_reachable_model_forbids_extra_keys() -> None:
    models = _reachable_models()
    open_models = sorted(
        f"{m.__module__}.{m.__qualname__}"
        for m in models
        if m.model_config.get("extra") != "forbid"
    )
    assert len(models) > 110  # the walk really covered both trees
    assert open_models == []


def _errors(doc: dict[str, Any]) -> list[tuple[str, str]]:
    base = {"name": "strict", "prompt": "You are strict."}
    with pytest.raises(ValidationError) as excinfo:
        AgentDocument.model_validate({**base, **doc})
    return [(".".join(map(str, e["loc"])), e["type"]) for e in excinfo.value.errors()]


@pytest.mark.parametrize(
    ("doc", "loc"),
    [
        ({"memory": {"retenion_days": 30}}, "memory.retenion_days"),
        ({"memory": {"semantic": {"max_memory": 5}}}, "memory.semantic.max_memory"),
        (
            {"ingest": {"sources": ["./docs"], "chunking": {"sise": 3}}},
            "ingest.chunking.sise",
        ),
        ({"model": {"name": "gpt-5-mini", "temprature": 0.2}}, "model.temprature"),
        ({"guardrails": {"retry_policy": {"attempts": 3}}}, "guardrails.retry_policy.attempts"),
        (
            {"triggers": [{"type": "cron", "schedule": "* * * * *", "prompt": "p", "tz": "UTC"}]},
            "triggers.0.cron.tz",
        ),
        (
            {"tools": ["think", {"filesystem": {"permissions": {"alow": ["path=*"]}}}]},
            "tools.1.permissions.alow",
        ),
        (
            {
                "tools": [
                    {
                        "script": {
                            "scripts": [
                                {
                                    "name": "s",
                                    "body": "echo",
                                    "parameters": [{"name": "p", "tpye": "x"}],
                                }
                            ]
                        }
                    }
                ]
            },
            "tools.0.scripts.0.parameters.0.tpye",
        ),
    ],
)
def test_nested_typo_fails_at_its_path(doc: dict[str, Any], loc: str) -> None:
    assert (loc, "extra_forbidden") in _errors(doc)


def test_composition_typo_fails_at_its_path() -> None:
    errors = _errors(
        {
            "prompt": None,
            "agents": {
                "a": {
                    "prompt": "first",
                    "then": {
                        "to": ["b", "c"],
                        "strategy": "ensemble",
                        "ensemble": {"quorum": 2},
                    },
                },
                "b": "second",
                "c": "third",
            },
        }
    )
    assert ("agents.a.then.ensemble.quorum", "extra_forbidden") in errors


@pytest.mark.parametrize(
    ("document", "model", "loc"),
    [
        (
            {
                "apiVersion": "initrunner/v1",
                "kind": "Agent",
                "metadata": {"name": "env"},
                "spec": {"role": "You help.", "memroy": {}},
            },
            RoleDefinition,
            ("spec", "memroy"),
        ),
        (
            {
                "apiVersion": "initrunner/v1",
                "kind": "Team",
                "metadata": {"name": "crew"},
                "spec": {"personas": {"a": {"role": "p", "tols": []}, "b": "q"}},
            },
            TeamDefinition,
            ("spec", "personas", "a", "tols"),
        ),
        (
            {
                "apiVersion": "initrunner/v1",
                "kind": "Flow",
                "metadata": {"name": "pipe", "tags": ["x"]},
                "spec": {"agents": {"a": {"role": "a.yaml"}}},
            },
            FlowDefinition,
            ("metadata", "tags"),
        ),
    ],
    ids=["role-spec", "team-persona", "flow-metadata"],
)
def test_envelope_typo_fails_at_its_path(document, model, loc) -> None:
    with pytest.raises(ValidationError) as excinfo:
        model.model_validate(document)
    assert (loc, "extra_forbidden") in [(e["loc"], e["type"]) for e in excinfo.value.errors()]


def test_every_bad_tool_is_reported() -> None:
    errors = _errors(
        {
            "tools": [
                {"shell": {"allowd_commands": ["ls"]}},
                "think",
                {"type": "mcp"},
            ]
        }
    )
    assert ("tools.0.allowd_commands", "extra_forbidden") in errors
    assert ("tools.2", "value_error") in errors


def test_free_form_mappings_stay_open() -> None:
    doc = AgentDocument.model_validate(
        {
            "name": "open",
            "prompt": "You keep arbitrary keys.",
            "model": {
                "provider": "openai",
                "name": "gpt-5-mini",
                "extra_headers": {"X-Anything": "1"},
                "extra_body": {"vendor_flag": {"nested": True}},
            },
            "tools": [
                {"type": "my_plugin", "any_key": 1, "another": {"x": 2}},
                {
                    "mcp": {
                        "url": "https://mcp.example",
                        "transport": "sse",
                        "headers": {"X-A": "b"},
                    }
                },
            ],
            "output": {
                "type": "json_schema",
                "schema": {"type": "object", "x-vendor": True, "additionalProperties": False},
            },
            "deps_schema": {"anything": {"goes": "here"}},
        }
    )
    plugin = doc.tools[0]
    assert isinstance(plugin, PluginToolConfig)
    assert plugin.type == "my_plugin"
    assert plugin.config == {"any_key": 1, "another": {"x": 2}}
    assert doc.output.schema_ is not None
    assert doc.output.schema_["x-vendor"] is True


def test_output_schema_alias_survives_envelope_round_trip() -> None:
    """The envelope converter dumps field names (``schema_``); the flat model must accept them."""
    result = normalize_mapping(
        {
            "apiVersion": "initrunner/v1",
            "kind": "Agent",
            "metadata": {"name": "structured"},
            "spec": {
                "role": "You reply in JSON.",
                "output": {"type": "json_schema", "schema": {"type": "object"}},
            },
        }
    )
    assert result.document.output.schema_ == {"type": "object"}


def test_skill_frontmatter_ignores_unknown_top_level_keys() -> None:
    """agentskills.io frontmatter from other tools may carry keys InitRunner doesn't know."""
    fm = SkillFrontmatter.model_validate(
        {"name": "my-skill", "description": "d", "homepage": "https://example.com"}
    )
    assert fm.name == "my-skill"


def test_skill_frontmatter_tools_are_strict() -> None:
    with pytest.raises(ValidationError) as excinfo:
        SkillFrontmatter.model_validate(
            {"name": "my-skill", "description": "d", "tools": [{"type": "shell", "allowd": 1}]}
        )
    locs = [e["loc"] for e in excinfo.value.errors()]
    assert ("tools", 0, "allowd") in locs
