"""Tests for the native extended-thinking effort field on model config."""

import pytest
from pydantic import ValidationError

from initrunner.agent.schema.base import ModelConfig, PartialModelConfig


class TestThinkingFieldValidation:
    def test_default_is_none(self):
        m = ModelConfig(provider="openai", name="o3-mini")
        assert m.thinking is None

    @pytest.mark.parametrize("level", ["minimal", "low", "medium", "high", "xhigh"])
    def test_valid_levels_on_o_series(self, level):
        m = ModelConfig(provider="openai", name="o3-mini", thinking=level)
        assert m.thinking == level

    def test_false_disables_thinking(self):
        m = ModelConfig(provider="openai", name="o1", thinking=False)
        assert m.thinking is False

    def test_valid_on_gpt5_family(self):
        m = ModelConfig(provider="openai", name="gpt-5", thinking="high")
        assert m.thinking == "high"

    def test_valid_on_gpt5_point_one(self):
        # gpt-5.1+ accepts a reasoning effort, so thinking is allowed there too.
        m = ModelConfig(provider="openai", name="gpt-5.1", thinking="minimal")
        assert m.thinking == "minimal"

    def test_rejects_unknown_literal(self):
        bad_value: object = "ultra"  # widened so ty does not flag the invalid literal
        with pytest.raises(ValidationError):
            ModelConfig(provider="openai", name="o3", thinking=bad_value)  # type: ignore[arg-type]

    def test_rejects_anthropic_provider(self):
        with pytest.raises(ValidationError) as exc:
            ModelConfig(provider="anthropic", name="claude-sonnet-4-5", thinking="high")
        assert "OpenAI" in str(exc.value)

    def test_rejects_gpt5_chat(self):
        with pytest.raises(ValidationError) as exc:
            ModelConfig(provider="openai", name="gpt-5-chat", thinking="high")
        assert "OpenAI" in str(exc.value)

    def test_rejects_non_reasoning_openai_model(self):
        with pytest.raises(ValidationError) as exc:
            ModelConfig(provider="openai", name="gpt-4o", thinking="high")
        assert "OpenAI" in str(exc.value)

    def test_error_message_is_actionable(self):
        with pytest.raises(ValidationError) as exc:
            ModelConfig(provider="anthropic", name="claude-sonnet-4-5", thinking="medium")
        msg = str(exc.value)
        assert "thinking is only supported" in msg
        assert "anthropic:claude-sonnet-4-5" in msg


class TestSupportsThinking:
    def test_o_series_supported(self):
        assert ModelConfig(provider="openai", name="o1").supports_thinking()
        assert ModelConfig(provider="openai", name="o3-mini").supports_thinking()

    def test_gpt5_family_supported(self):
        assert ModelConfig(provider="openai", name="gpt-5").supports_thinking()
        assert ModelConfig(provider="openai", name="gpt-5.1").supports_thinking()

    def test_gpt5_chat_not_supported(self):
        assert not ModelConfig(provider="openai", name="gpt-5-chat").supports_thinking()

    def test_non_openai_not_supported(self):
        assert not ModelConfig(provider="anthropic", name="claude-sonnet-4-5").supports_thinking()

    def test_non_reasoning_openai_not_supported(self):
        assert not ModelConfig(provider="openai", name="gpt-4o").supports_thinking()


class TestPartialDeferredValidation:
    def test_thinking_allowed_when_provider_and_name_empty(self):
        # A partial config awaiting auto-detection must not reject thinking
        # before the provider/name are filled in.
        p = PartialModelConfig(thinking="high")
        assert p.thinking == "high"
        assert not p.supports_thinking()

    def test_thinking_rejected_once_provider_resolves_to_unsupported(self):
        with pytest.raises(ValidationError):
            PartialModelConfig(provider="anthropic", name="claude-sonnet-4-5", thinking="high")
