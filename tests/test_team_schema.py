"""Tests for team schema and loader."""

import textwrap

import pytest
from pydantic import ValidationError

from initrunner.agent.schema.base import ModelConfig
from initrunner.agent.schema.tools import FileSystemToolConfig
from initrunner.team.loader import TeamLoadError, load_team
from initrunner.team.schema import (
    PersonaConfig,
    TeamDefinition,
    TeamDocumentsConfig,
    TeamGuardrails,
    TeamSpec,
)


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


class TestPersonaConfig:
    def test_simple_string_normalized(self):
        """Plain strings in YAML are normalized to PersonaConfig by the field_validator."""
        data = _minimal_team_data()
        defn = TeamDefinition.model_validate(data)
        assert isinstance(defn.spec.personas["alpha"], PersonaConfig)
        assert defn.spec.personas["alpha"].role == "first persona"

    def test_extended_form(self):
        data = _minimal_team_data()
        data["spec"]["personas"]["alpha"] = {
            "role": "first persona",
            "model": {"provider": "anthropic", "name": "claude-sonnet-4-6"},
            "tools": [{"type": "think"}],
            "tools_mode": "replace",
            "environment": {"API_KEY": "secret"},
        }
        defn = TeamDefinition.model_validate(data)
        alpha = defn.spec.personas["alpha"]
        assert alpha.role == "first persona"
        assert alpha.model is not None
        assert alpha.model.provider == "anthropic"
        assert alpha.tools_mode == "replace"
        assert len(alpha.tools) == 1
        assert alpha.environment == {"API_KEY": "secret"}

    def test_mixed_simple_and_extended(self):
        data = _minimal_team_data()
        data["spec"]["personas"]["alpha"] = {
            "role": "extended alpha",
            "model": {"provider": "anthropic", "name": "claude-sonnet-4-6"},
        }
        # bravo stays as simple string
        defn = TeamDefinition.model_validate(data)
        assert defn.spec.personas["alpha"].model is not None
        assert defn.spec.personas["bravo"].model is None
        assert defn.spec.personas["bravo"].role == "second persona"

    def test_tools_mode_default(self):
        pc = PersonaConfig(role="test")
        assert pc.tools_mode == "extend"

    def test_tools_mode_replace(self):
        pc = PersonaConfig(role="test", tools_mode="replace")
        assert pc.tools_mode == "replace"

    def test_per_persona_model(self):
        pc = PersonaConfig(
            role="test",
            model=ModelConfig(provider="anthropic", name="claude-sonnet-4-6"),
        )
        assert pc.model is not None
        assert pc.model.provider == "anthropic"

    def test_per_persona_env(self):
        pc = PersonaConfig(role="test", environment={"FOO": "bar"})
        assert pc.environment == {"FOO": "bar"}

    def test_tools_parsing(self):
        pc = PersonaConfig.model_validate({"role": "test", "tools": [{"type": "think"}]})
        assert len(pc.tools) == 1


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
            personas={"aa": "first", "bb": "second"},  # type: ignore[invalid-argument-type]
        )
        assert len(spec.personas) == 2
        assert spec.tools == []
        assert spec.handoff_max_chars == 4000

    def test_with_guardrails(self):
        spec = TeamSpec(
            model=ModelConfig(provider="openai", name="gpt-5-mini"),
            personas={"aa": "first", "bb": "second"},  # type: ignore[invalid-argument-type]
            guardrails=TeamGuardrails(max_tokens_per_run=10000, team_token_budget=50000),
        )
        assert spec.guardrails.max_tokens_per_run == 10000
        assert spec.guardrails.team_token_budget == 50000

    def test_with_handoff_max_chars(self):
        spec = TeamSpec(
            model=ModelConfig(provider="openai", name="gpt-5-mini"),
            personas={"aa": "first", "bb": "second"},  # type: ignore[invalid-argument-type]
            handoff_max_chars=8000,
        )
        assert spec.handoff_max_chars == 8000

    def test_zero_handoff_rejected(self):
        with pytest.raises(ValidationError):
            TeamSpec(
                model=ModelConfig(provider="openai", name="gpt-5-mini"),
                personas={"aa": "first", "bb": "second"},  # type: ignore[invalid-argument-type]
                handoff_max_chars=0,
            )

    def test_single_persona_rejected(self):
        with pytest.raises(ValidationError, match="at least 2"):
            TeamSpec(
                model=ModelConfig(provider="openai", name="gpt-5-mini"),
                personas={"only-one": "lonely"},  # type: ignore[invalid-argument-type]
            )

    def test_invalid_persona_name_uppercase(self):
        with pytest.raises(ValidationError, match="Invalid persona name"):
            TeamSpec(
                model=ModelConfig(provider="openai", name="gpt-5-mini"),
                personas={"Alpha": "first", "bravo": "second"},  # type: ignore[invalid-argument-type]
            )

    def test_invalid_persona_name_leading_hyphen(self):
        with pytest.raises(ValidationError, match="Invalid persona name"):
            TeamSpec(
                model=ModelConfig(provider="openai", name="gpt-5-mini"),
                personas={"-alpha": "first", "bravo": "second"},  # type: ignore[invalid-argument-type]
            )

    def test_invalid_persona_name_trailing_hyphen(self):
        with pytest.raises(ValidationError, match="Invalid persona name"):
            TeamSpec(
                model=ModelConfig(provider="openai", name="gpt-5-mini"),
                personas={"alpha-": "first", "bravo": "second"},  # type: ignore[invalid-argument-type]
            )

    def test_missing_model_accepted(self):
        """Model is optional -- will be auto-detected at runtime."""
        spec = TeamSpec(personas={"aa": "first", "bb": "second"})  # type: ignore[invalid-argument-type]
        assert spec.model is None

    def test_tool_parsing(self):
        spec = TeamSpec(
            model=ModelConfig(provider="openai", name="gpt-5-mini"),
            personas={"aa": "first", "bb": "second"},  # type: ignore[invalid-argument-type]
            tools=[FileSystemToolConfig(root_path="/tmp", read_only=True)],
        )
        assert len(spec.tools) == 1
        assert spec.tools[0].type == "filesystem"

    def test_shared_memory_defaults(self):
        spec = TeamSpec(
            model=ModelConfig(provider="openai", name="gpt-5-mini"),
            personas={"aa": "first", "bb": "second"},  # type: ignore[invalid-argument-type]
        )
        assert spec.shared_memory.enabled is False

    def test_shared_memory_enabled(self):
        spec = TeamSpec(
            model=ModelConfig(provider="openai", name="gpt-5-mini"),
            personas={"aa": "first", "bb": "second"},  # type: ignore[invalid-argument-type]
            shared_memory={"enabled": True, "max_memories": 500},  # type: ignore[invalid-argument-type]
        )
        assert spec.shared_memory.enabled is True
        assert spec.shared_memory.max_memories == 500

    def test_shared_documents_enabled(self):
        spec = TeamSpec(
            model=ModelConfig(provider="openai", name="gpt-5-mini"),
            personas={"aa": "first", "bb": "second"},  # type: ignore[invalid-argument-type]
            shared_documents={  # type: ignore[invalid-argument-type]
                "enabled": True,
                "sources": ["./docs/*.md"],
                "embeddings": {"provider": "openai", "model": "text-embedding-3-small"},
            },
        )
        assert spec.shared_documents.enabled is True
        assert spec.shared_documents.sources == ["./docs/*.md"]

    def test_shared_documents_requires_embeddings(self):
        with pytest.raises(ValidationError, match=r"embeddings\.provider is required"):
            TeamSpec(
                model=ModelConfig(provider="openai", name="gpt-5-mini"),
                personas={"aa": "first", "bb": "second"},  # type: ignore[invalid-argument-type]
                shared_documents={"enabled": True},  # type: ignore[invalid-argument-type]
            )

    def test_strategy_default(self):
        spec = TeamSpec(
            model=ModelConfig(provider="openai", name="gpt-5-mini"),
            personas={"aa": "first", "bb": "second"},  # type: ignore[invalid-argument-type]
        )
        assert spec.strategy == "sequential"

    def test_strategy_parallel(self):
        spec = TeamSpec(
            model=ModelConfig(provider="openai", name="gpt-5-mini"),
            personas={"aa": "first", "bb": "second"},  # type: ignore[invalid-argument-type]
            strategy="parallel",
        )
        assert spec.strategy == "parallel"

    def test_strategy_invalid(self):
        with pytest.raises(ValidationError):
            TeamSpec(
                model=ModelConfig(provider="openai", name="gpt-5-mini"),
                personas={"aa": "first", "bb": "second"},  # type: ignore[invalid-argument-type]
                strategy="round-robin",  # type: ignore[invalid-argument-type]
            )

    def test_observability_config(self):
        spec = TeamSpec(
            model=ModelConfig(provider="openai", name="gpt-5-mini"),
            personas={"aa": "first", "bb": "second"},  # type: ignore[invalid-argument-type]
            observability={"backend": "console"},  # type: ignore[invalid-argument-type]
        )
        assert spec.observability is not None
        assert spec.observability.backend == "console"

    def test_backward_compat_simple_personas(self):
        """Old string-only persona format still works."""
        spec = TeamSpec(
            model=ModelConfig(provider="openai", name="gpt-5-mini"),
            personas={"aa": "first role", "bb": "second role"},  # type: ignore[invalid-argument-type]
        )
        assert spec.personas["aa"].role == "first role"
        assert spec.personas["bb"].role == "second role"
        assert spec.personas["aa"].model is None
        assert spec.personas["aa"].tools == []

    def test_parallel_rejects_persona_env(self):
        with pytest.raises(ValidationError, match="not supported with strategy='parallel'"):
            TeamSpec(
                model=ModelConfig(provider="openai", name="gpt-5-mini"),
                personas={  # type: ignore[invalid-argument-type]
                    "aa": {"role": "first", "environment": {"FOO": "bar"}},
                    "bb": "second",
                },
                strategy="parallel",
            )

    def test_parallel_allows_no_env_personas(self):
        """Parallel is fine when no personas have env vars."""
        spec = TeamSpec(
            model=ModelConfig(provider="openai", name="gpt-5-mini"),
            personas={"aa": "first", "bb": "second"},  # type: ignore[invalid-argument-type]
            strategy="parallel",
        )
        assert spec.strategy == "parallel"


    def test_debate_strategy_accepted(self):
        spec = TeamSpec(
            model=ModelConfig(provider="openai", name="gpt-5-mini"),
            personas={"aa": "first", "bb": "second"},  # type: ignore[invalid-argument-type]
            strategy="debate",
        )
        assert spec.strategy == "debate"
        assert spec.debate.max_rounds == 3
        assert spec.debate.synthesize is True

    def test_debate_custom_config(self):
        spec = TeamSpec(
            model=ModelConfig(provider="openai", name="gpt-5-mini"),
            personas={"aa": "first", "bb": "second"},  # type: ignore[invalid-argument-type]
            strategy="debate",
            debate={"max_rounds": 5, "synthesize": False},
        )
        assert spec.debate.max_rounds == 5
        assert spec.debate.synthesize is False

    def test_debate_max_rounds_too_low(self):
        with pytest.raises(ValidationError, match="greater than or equal to 2"):
            TeamSpec(
                model=ModelConfig(provider="openai", name="gpt-5-mini"),
                personas={"aa": "first", "bb": "second"},  # type: ignore[invalid-argument-type]
                strategy="debate",
                debate={"max_rounds": 1},
            )

    def test_debate_max_rounds_too_high(self):
        with pytest.raises(ValidationError, match="less than or equal to 10"):
            TeamSpec(
                model=ModelConfig(provider="openai", name="gpt-5-mini"),
                personas={"aa": "first", "bb": "second"},  # type: ignore[invalid-argument-type]
                strategy="debate",
                debate={"max_rounds": 11},
            )

    def test_debate_rejects_persona_env(self):
        with pytest.raises(ValidationError, match="not supported with strategy='debate'"):
            TeamSpec(
                model=ModelConfig(provider="openai", name="gpt-5-mini"),
                personas={  # type: ignore[invalid-argument-type]
                    "aa": {"role": "first", "environment": {"FOO": "bar"}},
                    "bb": "second",
                },
                strategy="debate",
            )


class TestTeamDocumentsConfig:
    def test_disabled_defaults(self):
        cfg = TeamDocumentsConfig()
        assert cfg.enabled is False
        assert cfg.sources == []

    def test_enabled_requires_embeddings(self):
        with pytest.raises(ValidationError, match=r"embeddings\.provider"):
            TeamDocumentsConfig(enabled=True)

    def test_enabled_with_embeddings(self):
        cfg = TeamDocumentsConfig(
            enabled=True,
            sources=["./docs/*.md"],
            embeddings={"provider": "openai", "model": "text-embedding-3-small"},  # type: ignore[invalid-argument-type]
        )
        assert cfg.enabled is True
        assert cfg.sources == ["./docs/*.md"]

    def test_chunking_config(self):
        cfg = TeamDocumentsConfig(
            enabled=True,
            sources=["./data"],
            embeddings={"provider": "openai", "model": "text-embedding-3-small"},  # type: ignore[invalid-argument-type]
            chunking={"strategy": "paragraph", "chunk_size": 1024},  # type: ignore[invalid-argument-type]
        )
        assert cfg.chunking.strategy == "paragraph"
        assert cfg.chunking.chunk_size == 1024


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

    def test_full_v2_features(self):
        """End-to-end parse of a team spec using all v2 features."""
        data = _minimal_team_data()
        data["spec"]["personas"]["alpha"] = {
            "role": "alpha role",
            "model": {"provider": "anthropic", "name": "claude-sonnet-4-6"},
            "tools": [{"type": "think"}],
            "tools_mode": "extend",
            "environment": {"ALPHA_VAR": "1"},
        }
        data["spec"]["shared_memory"] = {"enabled": True, "max_memories": 500}
        data["spec"]["shared_documents"] = {
            "enabled": True,
            "sources": ["./docs/*.md"],
            "embeddings": {"provider": "openai", "model": "text-embedding-3-small"},
        }
        data["spec"]["observability"] = {"backend": "console"}
        data["spec"]["strategy"] = "sequential"

        defn = TeamDefinition.model_validate(data)
        assert defn.spec.shared_memory.enabled is True
        assert defn.spec.shared_documents.enabled is True
        assert defn.spec.observability is not None
        alpha = defn.spec.personas["alpha"]
        assert alpha.model is not None
        assert alpha.environment == {"ALPHA_VAR": "1"}


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

    def test_load_v2_features(self, tmp_path):
        yaml_content = textwrap.dedent("""\
            apiVersion: initrunner/v1
            kind: Team
            metadata:
              name: v2-team
            spec:
              model:
                provider: openai
                name: gpt-5-mini
              strategy: parallel
              personas:
                alpha: "simple persona"
                bravo:
                  role: "extended persona"
                  model:
                    provider: anthropic
                    name: claude-sonnet-4-6
                  tools:
                    - type: think
              shared_memory:
                enabled: true
              observability:
                backend: console
        """)
        f = tmp_path / "team.yaml"
        f.write_text(yaml_content)
        defn = load_team(f)
        assert defn.spec.strategy == "parallel"
        assert defn.spec.personas["alpha"].role == "simple persona"
        assert defn.spec.personas["bravo"].model is not None
        assert defn.spec.shared_memory.enabled is True
