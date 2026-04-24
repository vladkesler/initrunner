"""Tests for PydanticAI Agent Spec import."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from initrunner.agent.loader import load_role
from initrunner.services.agent_spec_import import (
    AgentSpecImportError,
    agent_spec_to_role_dict,
    load_agent_spec,
)


def _dump_and_load(spec: dict, tmp_path: Path, name: str = "spec.yaml") -> Path:
    p = tmp_path / name
    p.write_text(yaml.safe_dump(spec, sort_keys=False))
    return p


class TestAgentSpecToRoleDict:
    def test_minimal(self):
        role = agent_spec_to_role_dict(
            {"model": "anthropic:claude-sonnet-4-5", "instructions": "hi"},
            fallback_name="fallback",
        )
        assert role["apiVersion"] == "initrunner/v1"
        assert role["metadata"]["name"] == "fallback"
        assert role["spec"]["role"] == "hi"
        assert role["spec"]["model"] == {
            "provider": "anthropic",
            "name": "claude-sonnet-4-5",
        }

    def test_name_precedence_spec_name(self):
        role = agent_spec_to_role_dict(
            {
                "model": "anthropic:claude-sonnet-4-5",
                "name": "from-spec",
                "metadata": {"name": "from-metadata"},
            },
            fallback_name="from-stem",
        )
        assert role["metadata"]["name"] == "from-spec"

    def test_name_precedence_metadata_name(self):
        role = agent_spec_to_role_dict(
            {
                "model": "anthropic:claude-sonnet-4-5",
                "metadata": {"name": "from-metadata"},
            },
            fallback_name="from-stem",
        )
        assert role["metadata"]["name"] == "from-metadata"

    def test_name_precedence_stem_fallback(self):
        role = agent_spec_to_role_dict(
            {"model": "anthropic:claude-sonnet-4-5"},
            fallback_name="from-stem",
        )
        assert role["metadata"]["name"] == "from-stem"

    def test_execution_fields_mapped(self):
        role = agent_spec_to_role_dict(
            {
                "model": "openai:gpt-4o",
                "retries": 3,
                "output_retries": 2,
                "end_strategy": "exhaustive",
                "tool_timeout": 12.5,
            },
            fallback_name="f",
        )
        assert role["spec"]["execution"] == {
            "retries": 3,
            "output_retries": 2,
            "end_strategy": "exhaustive",
            "tool_timeout_seconds": 12.5,
        }

    def test_instructions_list_joined(self):
        role = agent_spec_to_role_dict(
            {
                "model": "openai:gpt-4o",
                "instructions": ["first rule", "second rule"],
            },
            fallback_name="f",
        )
        assert role["spec"]["role"] == "first rule\n\nsecond rule"

    def test_model_settings_extracted(self):
        role = agent_spec_to_role_dict(
            {
                "model": "openai:gpt-4o",
                "model_settings": {"max_tokens": 2048, "temperature": 0.2, "top_p": 0.9},
            },
            fallback_name="f",
        )
        assert role["spec"]["model"]["max_tokens"] == 2048
        assert role["spec"]["model"]["temperature"] == 0.2
        assert any("top_p" in w for w in role["_import_warnings"])

    def test_instrument_warned(self):
        role = agent_spec_to_role_dict(
            {"model": "openai:gpt-4o", "instrument": True}, fallback_name="f"
        )
        assert any("instrument" in w for w in role["_import_warnings"])

    def test_deps_schema_preserved_verbatim(self):
        schema = {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        }
        role = agent_spec_to_role_dict(
            {
                "model": "openai:gpt-4o",
                "instructions": "hi {{name}}",
                "deps_schema": schema,
            },
            fallback_name="f",
        )
        assert role["spec"]["deps_schema"] == schema
        assert role["spec"]["role"] == "hi {{name}}"

    def test_output_schema_mapped(self):
        role = agent_spec_to_role_dict(
            {
                "model": "openai:gpt-4o",
                "output_schema": {"type": "object", "properties": {"x": {"type": "string"}}},
            },
            fallback_name="f",
        )
        assert role["spec"]["output"]["type"] == "json_schema"
        assert role["spec"]["output"]["schema"]["type"] == "object"

    def test_invalid_end_strategy_errors(self):
        with pytest.raises(AgentSpecImportError, match="end_strategy"):
            agent_spec_to_role_dict(
                {"model": "openai:gpt-4o", "end_strategy": "neither"}, fallback_name="f"
            )

    def test_missing_model_errors(self):
        with pytest.raises(AgentSpecImportError, match="model"):
            agent_spec_to_role_dict({"instructions": "hi"}, fallback_name="f")

    def test_unresolvable_model_errors(self):
        with pytest.raises(AgentSpecImportError, match="resolve"):
            agent_spec_to_role_dict({"model": "not-an-alias"}, fallback_name="f")


class TestLoadAgentSpec:
    def test_round_trip_through_load_role(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        spec_path = _dump_and_load(
            {
                "model": "anthropic:claude-sonnet-4-5",
                "name": "greeter",
                "description": "says hi",
                "instructions": "you are helpful",
                "retries": 2,
                "end_strategy": "exhaustive",
            },
            tmp_path,
        )
        role_dict = load_agent_spec(spec_path)
        role_dict.pop("_import_warnings", None)
        out = tmp_path / "role.yaml"
        out.write_text(yaml.safe_dump(role_dict, sort_keys=False))
        role = load_role(out)
        assert role.metadata.name == "greeter"
        assert role.metadata.description == "says hi"
        assert role.spec.execution.retries == 2
        assert role.spec.execution.end_strategy == "exhaustive"

    def test_stem_fallback_when_no_name(self, tmp_path: Path):
        spec_path = _dump_and_load(
            {"model": "openai:gpt-4o", "instructions": "hi"},
            tmp_path,
            name="my-agent.yaml",
        )
        role_dict = load_agent_spec(spec_path)
        assert role_dict["metadata"]["name"] == "my-agent"
