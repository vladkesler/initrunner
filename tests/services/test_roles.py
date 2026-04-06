"""Tests for initrunner.services.roles -- canonicalize_role_yaml."""

from __future__ import annotations

from typing import Any

import yaml

from initrunner.agent.schema.autonomy import AutonomyConfig
from initrunner.agent.schema.base import ApiVersion, Kind, ModelConfig, RoleMetadata
from initrunner.agent.schema.memory import MemoryConfig
from initrunner.agent.schema.observability import ObservabilityConfig
from initrunner.agent.schema.reasoning import ReasoningConfig
from initrunner.agent.schema.role import AgentSpec, RoleDefinition
from initrunner.services.roles import canonicalize_role_yaml


def _make_role(**spec_kwargs: Any) -> RoleDefinition:
    """Build a minimal RoleDefinition for canonicalization tests."""
    return RoleDefinition(
        apiVersion=ApiVersion.V1,
        kind=Kind.AGENT,
        metadata=RoleMetadata(name="test-agent"),
        spec=AgentSpec(
            role="You are a test.",
            model=ModelConfig(provider="openai", name="gpt-5-mini"),
            **spec_kwargs,
        ),
    )


class TestCanonicalizePresenceSignificant:
    """Presence-significant optional sections survive canonicalization."""

    def test_memory_all_defaults_preserved(self) -> None:
        role = _make_role(memory=MemoryConfig())
        parsed = yaml.safe_load(canonicalize_role_yaml(role))
        assert "memory" in parsed["spec"]

    def test_autonomy_all_defaults_preserved(self) -> None:
        role = _make_role(autonomy=AutonomyConfig())
        parsed = yaml.safe_load(canonicalize_role_yaml(role))
        assert "autonomy" in parsed["spec"]

    def test_reasoning_all_defaults_preserved(self) -> None:
        role = _make_role(reasoning=ReasoningConfig())
        parsed = yaml.safe_load(canonicalize_role_yaml(role))
        assert "reasoning" in parsed["spec"]

    def test_observability_all_defaults_preserved(self) -> None:
        role = _make_role(observability=ObservabilityConfig())
        parsed = yaml.safe_load(canonicalize_role_yaml(role))
        assert "observability" in parsed["spec"]

    def test_absent_sections_stay_absent(self) -> None:
        role = _make_role()
        parsed = yaml.safe_load(canonicalize_role_yaml(role))
        spec = parsed["spec"]
        for key in ("memory", "ingest", "autonomy", "reasoning", "observability"):
            assert key not in spec, f"{key} should not appear when not set"

    def test_multiple_default_only_sections_together(self) -> None:
        role = _make_role(
            memory=MemoryConfig(),
            autonomy=AutonomyConfig(),
            reasoning=ReasoningConfig(),
        )
        parsed = yaml.safe_load(canonicalize_role_yaml(role))
        assert "memory" in parsed["spec"]
        assert "autonomy" in parsed["spec"]
        assert "reasoning" in parsed["spec"]
        assert "observability" not in parsed["spec"]

    def test_memory_with_non_default_values_preserved(self) -> None:
        role = _make_role(memory=MemoryConfig(max_sessions=5))
        parsed = yaml.safe_load(canonicalize_role_yaml(role))
        assert parsed["spec"]["memory"]["max_sessions"] == 5


# ---------------------------------------------------------------------------
# _detect_provider -- precedence tests
# ---------------------------------------------------------------------------


class TestDetectProvider:
    """_detect_provider should respect the canonical precedence contract."""

    def test_run_yaml_overrides_env_vars(self, monkeypatch):
        """run.yaml provider wins over env-var auto-detection."""
        from unittest.mock import patch

        from initrunner.services.roles import _detect_provider

        with patch(
            "initrunner.agent.loader.detect_default_model",
            return_value=("openai", "gpt-5-mini", None, None, "run_yaml"),
        ):
            assert _detect_provider() == "openai"

    def test_env_detection_used_when_no_run_yaml(self, monkeypatch):
        """Falls back to env auto-detection when run.yaml has no provider."""
        from unittest.mock import patch

        from initrunner.services.roles import _detect_provider

        with patch(
            "initrunner.agent.loader.detect_default_model",
            return_value=("anthropic", "claude-sonnet-4-6", None, None, "auto_detected"),
        ):
            assert _detect_provider() == "anthropic"

    def test_defaults_to_openai_when_nothing_configured(self):
        """Returns 'openai' when detect_default_model finds nothing."""
        from unittest.mock import patch

        from initrunner.services.roles import _detect_provider

        with patch(
            "initrunner.agent.loader.detect_default_model",
            return_value=("", "", None, None, "none"),
        ):
            assert _detect_provider() == "openai"

    def test_initrunner_model_env_takes_top_priority(self, monkeypatch):
        """INITRUNNER_MODEL env var wins over everything."""
        from unittest.mock import patch

        from initrunner.services.roles import _detect_provider

        with patch(
            "initrunner.agent.loader.detect_default_model",
            return_value=("google", "gemini-2.5-flash", None, None, "initrunner_model_env"),
        ):
            assert _detect_provider() == "google"
