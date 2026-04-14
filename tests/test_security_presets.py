"""Tests for security preset profiles."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from pydantic import ValidationError

from initrunner.agent.schema.security import (
    SECURITY_PRESETS,
    ContentPolicy,
    RateLimitConfig,
    SecurityPolicy,
    _resolve_preset_dict,
)

# ---------------------------------------------------------------------------
# Preset resolution
# ---------------------------------------------------------------------------


class TestPresetResolution:
    def test_public_preset_rate_limit(self) -> None:
        p = SecurityPolicy(preset="public")
        assert p.rate_limit.requests_per_minute == 30
        assert p.rate_limit.burst_size == 5

    def test_public_preset_content_policy(self) -> None:
        p = SecurityPolicy(preset="public")
        assert p.content.pii_redaction is True
        assert p.content.output_action == "block"
        assert p.content.max_prompt_length == 10_000
        assert len(p.content.blocked_input_patterns) == 3

    def test_public_preset_server(self) -> None:
        p = SecurityPolicy(preset="public")
        assert p.server.require_https is True

    def test_internal_preset_rate_limit(self) -> None:
        p = SecurityPolicy(preset="internal")
        assert p.rate_limit.requests_per_minute == 120
        assert p.rate_limit.burst_size == 20

    def test_internal_preset_content_at_defaults(self) -> None:
        p = SecurityPolicy(preset="internal")
        default_content = ContentPolicy()
        assert p.content.pii_redaction == default_content.pii_redaction
        assert p.content.max_prompt_length == default_content.max_prompt_length

    def test_sandbox_inherits_public(self) -> None:
        p = SecurityPolicy(preset="sandbox")
        assert p.rate_limit.requests_per_minute == 30
        assert p.content.pii_redaction is True
        assert p.server.require_https is True

    def test_sandbox_enables_docker(self) -> None:
        p = SecurityPolicy(preset="sandbox")
        assert p.docker.enabled is True
        assert p.docker.network == "none"
        assert p.docker.read_only_rootfs is True

    def test_development_preset_relaxes(self) -> None:
        p = SecurityPolicy(preset="development")
        assert p.rate_limit.requests_per_minute == 9999
        assert p.content.pii_redaction is False
        assert p.content.blocked_input_patterns == []
        assert p.content.max_prompt_length == 500_000
        assert p.docker.enabled is False

    def test_invalid_preset_raises(self) -> None:
        with pytest.raises(ValidationError, match="Unknown security preset"):
            SecurityPolicy(preset="nonexistent")  # type: ignore[arg-type]

    def test_extends_cycle_raises(self) -> None:
        with patch.dict(
            SECURITY_PRESETS,
            {"a": {"_extends": "b"}, "b": {"_extends": "a"}},
        ):
            with pytest.raises(ValueError, match="Circular"):
                _resolve_preset_dict("a")


# ---------------------------------------------------------------------------
# Overrides
# ---------------------------------------------------------------------------


class TestPresetOverrides:
    def test_override_single_subfield(self) -> None:
        p = SecurityPolicy.model_validate(
            {"preset": "public", "rate_limit": {"requests_per_minute": 100}}
        )
        assert p.rate_limit.requests_per_minute == 100
        assert p.rate_limit.burst_size == 5  # preserved from preset

    def test_override_preserves_other_preset_blocks(self) -> None:
        p = SecurityPolicy.model_validate(
            {"preset": "public", "rate_limit": {"requests_per_minute": 100}}
        )
        assert p.content.pii_redaction is True
        assert p.server.require_https is True

    def test_preset_field_preserved_after_override(self) -> None:
        p = SecurityPolicy.model_validate(
            {"preset": "public", "rate_limit": {"requests_per_minute": 100}}
        )
        assert p.preset == "public"

    def test_list_override_replaces(self) -> None:
        p = SecurityPolicy.model_validate(
            {"preset": "public", "content": {"blocked_input_patterns": []}}
        )
        assert p.content.blocked_input_patterns == []


# ---------------------------------------------------------------------------
# Labels
# ---------------------------------------------------------------------------


class TestEffectiveLabel:
    def test_default_label(self) -> None:
        p = SecurityPolicy()
        assert p.effective_label == "default"

    def test_preset_label(self) -> None:
        p = SecurityPolicy(preset="public")
        assert p.effective_label == "public"

    def test_custom_label(self) -> None:
        p = SecurityPolicy(rate_limit=RateLimitConfig(requests_per_minute=42))
        assert p.effective_label == "custom"

    def test_sandbox_label(self) -> None:
        p = SecurityPolicy(preset="sandbox")
        assert p.effective_label == "sandbox"


# ---------------------------------------------------------------------------
# Compact dump
# ---------------------------------------------------------------------------


class TestCompactDump:
    def test_preset_only(self) -> None:
        p = SecurityPolicy(preset="public")
        compact = p.compact_dump()
        assert compact == {"preset": "public"}

    def test_with_override(self) -> None:
        p = SecurityPolicy.model_validate(
            {"preset": "public", "rate_limit": {"requests_per_minute": 100}}
        )
        compact = p.compact_dump()
        assert compact["preset"] == "public"
        assert compact["rate_limit"] == {"requests_per_minute": 100}
        assert "content" not in compact
        assert "server" not in compact

    def test_no_preset_falls_back(self) -> None:
        p = SecurityPolicy(rate_limit=RateLimitConfig(requests_per_minute=42))
        compact = p.compact_dump()
        # Without preset, compact_dump == model_dump
        assert compact == p.model_dump()


# ---------------------------------------------------------------------------
# YAML round-trip
# ---------------------------------------------------------------------------


class TestYAMLRoundTrip:
    def test_role_yaml_with_preset(self) -> None:
        from initrunner.agent.schema.base import ApiVersion, Kind, ModelConfig, RoleMetadata
        from initrunner.agent.schema.role import AgentSpec, RoleDefinition

        role = RoleDefinition(
            apiVersion=ApiVersion.V1,
            kind=Kind.AGENT,
            metadata=RoleMetadata(name="test", spec_version=2),
            spec=AgentSpec(
                role="Test",
                model=ModelConfig(provider="openai", name="gpt-4o"),
                security=SecurityPolicy(preset="public"),
            ),
        )
        assert role.spec.security.preset == "public"
        assert role.spec.security.rate_limit.requests_per_minute == 30

    def test_role_yaml_preset_plus_override(self) -> None:
        from initrunner.agent.schema.base import ApiVersion, Kind, ModelConfig, RoleMetadata
        from initrunner.agent.schema.role import AgentSpec, RoleDefinition

        role = RoleDefinition(
            apiVersion=ApiVersion.V1,
            kind=Kind.AGENT,
            metadata=RoleMetadata(name="test", spec_version=2),
            spec=AgentSpec(
                role="Test",
                model=ModelConfig(provider="openai", name="gpt-4o"),
                security=SecurityPolicy.model_validate(
                    {"preset": "public", "rate_limit": {"requests_per_minute": 100}}
                ),
            ),
        )
        assert role.spec.security.rate_limit.requests_per_minute == 100
        assert role.spec.security.content.pii_redaction is True
