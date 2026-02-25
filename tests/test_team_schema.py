"""Tests for team schema and loader."""

import textwrap

import pytest
from pydantic import ValidationError

from initrunner.agent.schema.base import ModelConfig
from initrunner.agent.schema.tools import FileSystemToolConfig
from initrunner.team.loader import TeamLoadError, load_team
from initrunner.team.schema import TeamDefinition, TeamGuardrails, TeamSpec


def _minimal_team_data() -> dict:
    return {
        "apiVersion": "initrunner/v1",
        "kind": "Team",
        "metadata": {"name": "test-team"},
        "spec": {
            "model": {"provider": "openai", "name": "gpt-5-mini"},
            "personas": {
                "alpha": "first persona",
                "bravo": "second persona",
            },
        },
    }


class TestTeamGuardrails:
    def test_defaults(self):
        g = TeamGuardrails()
        assert g.max_tokens_per_run == 50000
        assert g.max_tool_calls == 20
        assert g.timeout_seconds == 300
        assert g.team_token_budget is None
        assert g.team_timeout_seconds is None

    def test_custom_values(self):
        g = TeamGuardrails(
            max_tokens_per_run=10000,
            max_tool_calls=5,
            timeout_seconds=60,
            team_token_budget=100000,
            team_timeout_seconds=600,
        )
        assert g.max_tokens_per_run == 10000
        assert g.team_token_budget == 100000
        assert g.team_timeout_seconds == 600

    def test_zero_tokens_rejected(self):
        with pytest.raises(ValidationError):
            TeamGuardrails(max_tokens_per_run=0)

    def test_zero_timeout_rejected(self):
        with pytest.raises(ValidationError):
            TeamGuardrails(timeout_seconds=0)


class TestTeamSpec:
    def test_minimal_valid(self):
        spec = TeamSpec(
            model=ModelConfig(provider="openai", name="gpt-5-mini"),
            personas={"aa": "first", "bb": "second"},
        )
        assert len(spec.personas) == 2
        assert spec.tools == []
        assert spec.handoff_max_chars == 4000

    def test_with_guardrails(self):
        spec = TeamSpec(
            model=ModelConfig(provider="openai", name="gpt-5-mini"),
            personas={"aa": "first", "bb": "second"},
            guardrails=TeamGuardrails(max_tokens_per_run=10000, team_token_budget=50000),
        )
        assert spec.guardrails.max_tokens_per_run == 10000
        assert spec.guardrails.team_token_budget == 50000

    def test_with_handoff_max_chars(self):
        spec = TeamSpec(
            model=ModelConfig(provider="openai", name="gpt-5-mini"),
            personas={"aa": "first", "bb": "second"},
            handoff_max_chars=8000,
        )
        assert spec.handoff_max_chars == 8000

    def test_zero_handoff_rejected(self):
        with pytest.raises(ValidationError):
            TeamSpec(
                model=ModelConfig(provider="openai", name="gpt-5-mini"),
                personas={"aa": "first", "bb": "second"},
                handoff_max_chars=0,
            )

    def test_single_persona_rejected(self):
        with pytest.raises(ValidationError, match="at least 2"):
            TeamSpec(
                model=ModelConfig(provider="openai", name="gpt-5-mini"),
                personas={"only-one": "lonely"},
            )

    def test_invalid_persona_name_uppercase(self):
        with pytest.raises(ValidationError, match="Invalid persona name"):
            TeamSpec(
                model=ModelConfig(provider="openai", name="gpt-5-mini"),
                personas={"Alpha": "first", "bravo": "second"},
            )

    def test_invalid_persona_name_leading_hyphen(self):
        with pytest.raises(ValidationError, match="Invalid persona name"):
            TeamSpec(
                model=ModelConfig(provider="openai", name="gpt-5-mini"),
                personas={"-alpha": "first", "bravo": "second"},
            )

    def test_invalid_persona_name_trailing_hyphen(self):
        with pytest.raises(ValidationError, match="Invalid persona name"):
            TeamSpec(
                model=ModelConfig(provider="openai", name="gpt-5-mini"),
                personas={"alpha-": "first", "bravo": "second"},
            )

    def test_missing_model_rejected(self):
        with pytest.raises(ValidationError):
            TeamSpec(personas={"aa": "first", "bb": "second"})  # type: ignore[missing-argument]

    def test_tool_parsing(self):
        spec = TeamSpec(
            model=ModelConfig(provider="openai", name="gpt-5-mini"),
            personas={"aa": "first", "bb": "second"},
            tools=[FileSystemToolConfig(root_path="/tmp", read_only=True)],
        )
        assert len(spec.tools) == 1
        assert spec.tools[0].type == "filesystem"


class TestTeamDefinition:
    def test_valid(self):
        data = _minimal_team_data()
        defn = TeamDefinition.model_validate(data)
        assert defn.kind == "Team"
        assert defn.metadata.name == "test-team"
        assert len(defn.spec.personas) == 2

    def test_wrong_kind_rejected(self):
        data = _minimal_team_data()
        data["kind"] = "Agent"
        with pytest.raises(ValidationError, match="kind"):
            TeamDefinition.model_validate(data)

    def test_wrong_api_version_rejected(self):
        data = _minimal_team_data()
        data["apiVersion"] = "wrong/v99"
        with pytest.raises(ValidationError):
            TeamDefinition.model_validate(data)

    def test_with_tools_and_guardrails(self):
        data = _minimal_team_data()
        data["spec"]["tools"] = [{"type": "filesystem", "root_path": "/tmp", "read_only": True}]
        data["spec"]["guardrails"] = {
            "max_tokens_per_run": 25000,
            "team_token_budget": 100000,
        }
        defn = TeamDefinition.model_validate(data)
        assert len(defn.spec.tools) == 1
        assert defn.spec.guardrails.team_token_budget == 100000

    def test_three_personas(self):
        data = _minimal_team_data()
        data["spec"]["personas"]["charlie"] = "third persona"
        defn = TeamDefinition.model_validate(data)
        assert len(defn.spec.personas) == 3


class TestTeamLoader:
    def test_load_valid(self, tmp_path):
        yaml_content = textwrap.dedent("""\
            apiVersion: initrunner/v1
            kind: Team
            metadata:
              name: my-team
            spec:
              model:
                provider: openai
                name: gpt-5-mini
              personas:
                reviewer: "review code"
                tester: "write tests"
        """)
        f = tmp_path / "team.yaml"
        f.write_text(yaml_content)
        defn = load_team(f)
        assert defn.metadata.name == "my-team"
        assert len(defn.spec.personas) == 2

    def test_load_missing_file(self, tmp_path):
        with pytest.raises(TeamLoadError, match="Cannot read"):
            load_team(tmp_path / "nope.yaml")

    def test_load_invalid_yaml(self, tmp_path):
        f = tmp_path / "bad.yaml"
        f.write_text(": invalid: yaml: [")
        with pytest.raises(TeamLoadError, match="Invalid YAML"):
            load_team(f)

    def test_load_not_mapping(self, tmp_path):
        f = tmp_path / "list.yaml"
        f.write_text("- item1\n- item2\n")
        with pytest.raises(TeamLoadError, match="Expected a YAML mapping"):
            load_team(f)

    def test_load_validation_error(self, tmp_path):
        f = tmp_path / "bad.yaml"
        f.write_text("apiVersion: initrunner/v1\nkind: Team\n")
        with pytest.raises(TeamLoadError, match="Validation failed"):
            load_team(f)
