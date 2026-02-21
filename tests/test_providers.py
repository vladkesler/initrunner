"""Tests for the provider auto-detection service."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from initrunner.services.providers import (
    build_ephemeral_role,
    detect_bot_tokens,
    detect_provider_and_model,
)

# Patch _load_env to prevent .env files in cwd from polluting tests
_MOCK_LOAD_ENV = patch("initrunner.services.providers._load_env")


@pytest.fixture()
def clean_env(monkeypatch, tmp_path):
    """Remove all provider API keys and bot tokens from the env."""
    for var in (
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "GOOGLE_API_KEY",
        "GROQ_API_KEY",
        "MISTRAL_API_KEY",
        "CO_API_KEY",
        "TELEGRAM_BOT_TOKEN",
        "DISCORD_BOT_TOKEN",
    ):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("INITRUNNER_HOME", str(tmp_path / "home"))
    from initrunner.config import get_home_dir

    get_home_dir.cache_clear()
    yield tmp_path
    get_home_dir.cache_clear()


class TestDetectProviderAndModel:
    def test_anthropic_before_openai(self, clean_env, monkeypatch):
        """Anthropic takes priority when both keys are set."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        with _MOCK_LOAD_ENV:
            result = detect_provider_and_model()
        assert result is not None
        assert result.provider == "anthropic"

    def test_openai_detected(self, clean_env, monkeypatch):
        """OpenAI detected when only its key is set."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        with _MOCK_LOAD_ENV:
            result = detect_provider_and_model()
        assert result is not None
        assert result.provider == "openai"

    def test_google_detected(self, clean_env, monkeypatch):
        monkeypatch.setenv("GOOGLE_API_KEY", "test-key")
        with _MOCK_LOAD_ENV:
            result = detect_provider_and_model()
        assert result is not None
        assert result.provider == "google"

    def test_groq_detected(self, clean_env, monkeypatch):
        monkeypatch.setenv("GROQ_API_KEY", "test-key")
        with _MOCK_LOAD_ENV:
            result = detect_provider_and_model()
        assert result is not None
        assert result.provider == "groq"

    def test_mistral_detected(self, clean_env, monkeypatch):
        monkeypatch.setenv("MISTRAL_API_KEY", "test-key")
        with _MOCK_LOAD_ENV:
            result = detect_provider_and_model()
        assert result is not None
        assert result.provider == "mistral"

    def test_cohere_detected(self, clean_env, monkeypatch):
        monkeypatch.setenv("CO_API_KEY", "test-key")
        with _MOCK_LOAD_ENV:
            result = detect_provider_and_model()
        assert result is not None
        assert result.provider == "cohere"

    def test_none_when_no_keys(self, clean_env):
        """Returns None when no API keys and no Ollama."""
        with (
            _MOCK_LOAD_ENV,
            patch("initrunner.services.providers._is_ollama_running", return_value=False),
        ):
            result = detect_provider_and_model()
        assert result is None

    def test_ollama_fallback(self, clean_env):
        """Falls back to Ollama when running locally."""
        with (
            _MOCK_LOAD_ENV,
            patch("initrunner.services.providers._is_ollama_running", return_value=True),
            patch(
                "initrunner.services.providers._get_first_ollama_model",
                return_value="mistral",
            ),
        ):
            result = detect_provider_and_model()
        assert result is not None
        assert result.provider == "ollama"
        assert result.model == "mistral"

    def test_ollama_fallback_default_model(self, clean_env):
        """When Ollama has no models, defaults to llama3.2."""
        with (
            _MOCK_LOAD_ENV,
            patch("initrunner.services.providers._is_ollama_running", return_value=True),
            patch(
                "initrunner.services.providers._get_first_ollama_model",
                return_value=None,
            ),
        ):
            result = detect_provider_and_model()
        assert result is not None
        assert result.provider == "ollama"
        assert result.model == "llama3.2"

    def test_dotenv_loading(self, clean_env):
        """Reads API key from global .env file via _load_env."""
        tmp_path = clean_env
        home = tmp_path / "home"
        home.mkdir(parents=True, exist_ok=True)
        (home / ".env").write_text('OPENAI_API_KEY="sk-from-dotenv"\n')

        # Don't mock _load_env here — we want it to actually load the .env
        with patch("initrunner.services.providers._is_ollama_running", return_value=False):
            result = detect_provider_and_model()
        assert result is not None
        assert result.provider == "openai"

    def test_default_model_returned(self, clean_env, monkeypatch):
        """Provider detection includes a default model name."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        with _MOCK_LOAD_ENV:
            result = detect_provider_and_model()
        assert result is not None
        assert result.model  # Should be non-empty


class TestDetectBotTokens:
    def test_no_tokens(self, clean_env):
        with _MOCK_LOAD_ENV:
            assert detect_bot_tokens() == {}

    def test_telegram_token(self, clean_env, monkeypatch):
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
        with _MOCK_LOAD_ENV:
            result = detect_bot_tokens()
        assert "telegram" in result
        assert result["telegram"] == "TELEGRAM_BOT_TOKEN"

    def test_discord_token(self, clean_env, monkeypatch):
        monkeypatch.setenv("DISCORD_BOT_TOKEN", "token-abc")
        with _MOCK_LOAD_ENV:
            result = detect_bot_tokens()
        assert "discord" in result

    def test_both_tokens(self, clean_env, monkeypatch):
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
        monkeypatch.setenv("DISCORD_BOT_TOKEN", "token-abc")
        with _MOCK_LOAD_ENV:
            result = detect_bot_tokens()
        assert len(result) == 2


class TestBuildEphemeralRole:
    def test_minimal_role(self):
        role = build_ephemeral_role("openai", "gpt-5-mini")
        assert role.metadata.name == "ephemeral-chat"
        assert role.spec.model.provider == "openai"
        assert role.spec.model.name == "gpt-5-mini"
        assert role.spec.triggers == []
        assert role.spec.autonomy is None

    def test_custom_name_and_prompt(self):
        role = build_ephemeral_role(
            "anthropic",
            "claude-sonnet-4-5-20250929",
            name="my-bot",
            system_prompt="You are a pirate.",
        )
        assert role.metadata.name == "my-bot"
        assert "pirate" in role.spec.role

    def test_with_triggers(self):
        from initrunner.agent.schema.triggers import TelegramTriggerConfig

        trigger = TelegramTriggerConfig(autonomous=True)
        role = build_ephemeral_role(
            "openai",
            "gpt-5-mini",
            triggers=[trigger],
        )
        assert len(role.spec.triggers) == 1
        assert role.spec.triggers[0].type == "telegram"

    def test_with_autonomy(self):
        role = build_ephemeral_role(
            "openai",
            "gpt-5-mini",
            autonomy={},
        )
        assert role.spec.autonomy is not None

    def test_with_tools(self):
        role = build_ephemeral_role(
            "openai",
            "gpt-5-mini",
            tools=[{"type": "datetime"}],
        )
        assert len(role.spec.tools) == 1

    def test_with_guardrails(self):
        role = build_ephemeral_role(
            "openai",
            "gpt-5-mini",
            guardrails={"daemon_daily_token_budget": 200_000},
        )
        assert role.spec.guardrails.daemon_daily_token_budget == 200_000

    def test_role_validates(self):
        """Built role passes Pydantic validation."""
        from initrunner.agent.schema.triggers import DiscordTriggerConfig

        trigger = DiscordTriggerConfig(autonomous=True)
        role = build_ephemeral_role(
            "anthropic",
            "claude-sonnet-4-5-20250929",
            name="test-bot",
            triggers=[trigger],
            tools=[{"type": "datetime"}, {"type": "web_reader"}],
            autonomy={},
            guardrails={"daemon_daily_token_budget": 200_000},
        )
        assert role.apiVersion.value == "initrunner/v1"
        assert role.kind.value == "Agent"
        assert role.spec.autonomy is not None
        assert len(role.spec.triggers) == 1
        assert len(role.spec.tools) == 2
