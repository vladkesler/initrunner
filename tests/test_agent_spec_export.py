"""Tests for role.yaml -> PydanticAI Agent Spec export."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
import yaml

from initrunner.agent.loader import load_role
from initrunner.services.agent_spec_export import role_to_agent_spec


def _write_role(tmp_path: Path, extra: str = "") -> Path:
    content = textwrap.dedent(f"""\
        apiVersion: initrunner/v1
        kind: Agent
        metadata:
          name: greeter
          description: says hi
        spec:
          role: hello world
          model:
            provider: openai
            name: gpt-4o
            temperature: 0.2
            max_tokens: 2048
          {extra}
    """)
    p = tmp_path / "role.yaml"
    p.write_text(content)
    return p


class TestRoleToAgentSpec:
    def test_overlap_fields_only(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        role = load_role(_write_role(tmp_path))
        spec, dropped = role_to_agent_spec(role)
        assert spec["name"] == "greeter"
        assert spec["description"] == "says hi"
        assert spec["model"] == "openai:gpt-4o"
        assert spec["model_settings"] == {"max_tokens": 2048, "temperature": 0.2}
        assert spec["instructions"] == "hello world"
        # Default execution fields omitted
        assert "retries" not in spec
        assert "end_strategy" not in spec
        assert dropped.names == []

    def test_execution_non_default_emitted(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        extra = (
            "execution:\n"
            "            retries: 3\n"
            "            output_retries: 2\n"
            "            end_strategy: exhaustive\n"
            "            tool_timeout_seconds: 10.0"
        )
        role = load_role(_write_role(tmp_path, extra))
        spec, _ = role_to_agent_spec(role)
        assert spec["retries"] == 3
        assert spec["output_retries"] == 2
        assert spec["end_strategy"] == "exhaustive"
        assert spec["tool_timeout"] == 10.0

    def test_dropped_sections_reported(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        extra = (
            "tools:\n"
            "            - type: datetime\n"
            "          triggers:\n"
            "            - type: cron\n"
            "              schedule: '0 * * * *'\n"
            "              prompt: do work"
        )
        role = load_role(_write_role(tmp_path, extra))
        _, dropped = role_to_agent_spec(role)
        assert "tools" in dropped.names
        assert "triggers" in dropped.names

    def test_round_trip_via_pydanticai(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """Emitted spec validates against PydanticAI's own AgentSpec."""
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        role = load_role(_write_role(tmp_path))
        spec, _ = role_to_agent_spec(role)

        # Sanity: round-trip through yaml
        dumped = yaml.safe_dump(spec, sort_keys=False)
        reloaded = yaml.safe_load(dumped)
        assert reloaded["model"] == "openai:gpt-4o"

        # Validate upstream (non-templated instructions, so no handlebars needed)
        from pydantic_ai.agent.spec import AgentSpec

        AgentSpec.model_validate(reloaded)


class TestMetadataRoundTrip:
    def test_metadata_exported(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        content = textwrap.dedent("""\
            apiVersion: initrunner/v1
            kind: Agent
            metadata:
              name: greeter
              description: says hi
              tags: [demo, greeting]
              author: jc
              team: platform
              version: "1.2"
            spec:
              role: hello world
              model:
                provider: openai
                name: gpt-4o
        """)
        p = tmp_path / "role.yaml"
        p.write_text(content)
        spec, _dropped = role_to_agent_spec(load_role(p))
        assert spec["metadata"] == {
            "tags": ["demo", "greeting"],
            "author": "jc",
            "team": "platform",
            "version": "1.2",
        }

    def test_metadata_omitted_when_empty(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        spec, _dropped = role_to_agent_spec(load_role(_write_role(tmp_path)))
        assert "metadata" not in spec

    def test_full_round_trip(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        from initrunner.services.agent_spec_import import agent_spec_to_role_dict

        content = textwrap.dedent("""\
            apiVersion: initrunner/v1
            kind: Agent
            metadata:
              name: greeter
              tags: [demo]
              author: jc
            spec:
              role: hello world
              model:
                provider: openai
                name: gpt-4o
        """)
        p = tmp_path / "role.yaml"
        p.write_text(content)
        spec, _dropped = role_to_agent_spec(load_role(p))
        role_dict = agent_spec_to_role_dict(spec, fallback_name="x")
        assert role_dict["metadata"]["tags"] == ["demo"]
        assert role_dict["metadata"]["author"] == "jc"
        assert "_import_warnings" not in role_dict
