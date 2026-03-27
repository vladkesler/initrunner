"""Tests for the setup orchestration service."""

from __future__ import annotations

from unittest.mock import patch

import pytest
import yaml

from initrunner.services.setup import (
    INTENT_TEMPLATE_MAP,
    SetupConfig,
    detect_existing_provider,
    generate_role_yaml,
    generate_run_yaml,
    needs_setup,
    provider_needs_embeddings_warning,
    save_env_key,
)

_MOCK_LOAD_ENV = patch("initrunner.services.providers._load_env")


@pytest.fixture()
def clean_env(monkeypatch, tmp_path):
    """Remove all provider API keys from the env."""
    for var in (
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "GOOGLE_API_KEY",
        "GROQ_API_KEY",
        "MISTRAL_API_KEY",
        "CO_API_KEY",
        "XAI_API_KEY",
        "TELEGRAM_BOT_TOKEN",
        "DISCORD_BOT_TOKEN",
    ):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("INITRUNNER_HOME", str(tmp_path / "home"))
    from initrunner.config import get_home_dir

    get_home_dir.cache_clear()
    yield tmp_path
    get_home_dir.cache_clear()


class TestNeedsSetup:
    def test_true_when_fresh(self, clean_env):
        with patch("initrunner.services.providers._is_ollama_running", return_value=False):
            assert needs_setup() is True

    def test_false_with_xai_key(self, clean_env, monkeypatch):
        monkeypatch.setenv("XAI_API_KEY", "xai-test")
        assert needs_setup() is False

    def test_false_with_openai_key(self, clean_env, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        assert needs_setup() is False

    def test_false_with_ollama_running(self, clean_env):
        with patch("initrunner.services.providers._is_ollama_running", return_value=True):
            assert needs_setup() is False


class TestDetectExistingProvider:
    def test_from_env(self, clean_env, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        result = detect_existing_provider()
        assert result is not None
        assert result[0] == "openai"
        assert result[1] == "OPENAI_API_KEY"

    def test_from_dotenv(self, clean_env):
        tmp_path = clean_env
        home = tmp_path / "home"
        home.mkdir(parents=True, exist_ok=True)
        (home / ".env").write_text('ANTHROPIC_API_KEY="sk-ant-test"\n')
        result = detect_existing_provider()
        assert result is not None
        assert result[0] == "anthropic"

    def test_xai(self, clean_env, monkeypatch):
        monkeypatch.setenv("XAI_API_KEY", "xai-test")
        result = detect_existing_provider()
        assert result is not None
        assert result[0] == "xai"
        assert result[1] == "XAI_API_KEY"

    def test_none_when_fresh(self, clean_env):
        result = detect_existing_provider()
        assert result is None


class TestProviderNeedsEmbeddingsWarning:
    @pytest.mark.parametrize(
        "provider,intent,expected",
        [
            ("openai", "knowledge", False),
            ("anthropic", "knowledge", True),
            ("anthropic", "chatbot", False),
            ("ollama", "memory", True),
            ("google", "knowledge", False),
            ("xai", "knowledge", True),
            ("groq", "memory", True),
            ("bedrock", "knowledge", True),
            ("cohere", "chatbot", False),
        ],
    )
    def test_warning(self, provider, intent, expected):
        assert provider_needs_embeddings_warning(provider, intent) is expected


class TestGenerateRoleYaml:
    def test_chatbot_intent(self):
        config = SetupConfig(intent="chatbot", provider="openai", model="gpt-5-mini")
        content = generate_role_yaml(config)
        data = yaml.safe_load(content)
        assert data["spec"]["model"]["provider"] == "openai"
        assert "You are a helpful assistant" in data["spec"]["role"]

    def test_knowledge_intent_has_ingest(self):
        config = SetupConfig(
            intent="knowledge",
            provider="openai",
            model="gpt-5-mini",
            ingest_sources=["./docs/**/*.md"],
        )
        content = generate_role_yaml(config)
        data = yaml.safe_load(content)
        assert "ingest" in data["spec"]
        assert data["spec"]["ingest"]["sources"] == ["./docs/**/*.md"]

    def test_ollama_with_knowledge_not_overridden(self):
        """BUG FIX TEST: Ollama + knowledge should produce RAG YAML, not ollama template."""
        config = SetupConfig(
            intent="knowledge",
            provider="ollama",
            model="llama3.2",
            ingest_sources=["./docs/**/*.md"],
        )
        content = generate_role_yaml(config)
        data = yaml.safe_load(content)
        assert "ingest" in data["spec"]
        assert data["spec"]["model"]["provider"] == "ollama"
        assert "knowledge assistant" in data["spec"]["role"].lower()

    def test_memory_intent(self):
        config = SetupConfig(intent="memory", provider="openai", model="gpt-5-mini")
        content = generate_role_yaml(config)
        data = yaml.safe_load(content)
        assert "memory" in data["spec"]

    def test_daemon_intent(self):
        config = SetupConfig(intent="daemon", provider="openai", model="gpt-5-mini")
        content = generate_role_yaml(config)
        data = yaml.safe_load(content)
        assert "triggers" in data["spec"]

    def test_telegram_intent(self):
        config = SetupConfig(intent="telegram-bot", provider="openai", model="gpt-5-mini")
        content = generate_role_yaml(config)
        assert "telegram" in content.lower()

    def test_discord_intent(self):
        config = SetupConfig(intent="discord-bot", provider="openai", model="gpt-5-mini")
        content = generate_role_yaml(config)
        assert "discord" in content.lower()

    def test_tools_included_in_output(self):
        config = SetupConfig(
            intent="chatbot",
            provider="openai",
            model="gpt-5-mini",
            tools=[{"type": "datetime"}, {"type": "web_reader"}],
        )
        content = generate_role_yaml(config)
        data = yaml.safe_load(content)
        assert "tools" in data["spec"]
        tool_types = [t["type"] for t in data["spec"]["tools"]]
        assert "datetime" in tool_types
        assert "web_reader" in tool_types

    @pytest.mark.parametrize("intent", list(INTENT_TEMPLATE_MAP.keys()))
    def test_every_intent_produces_valid_yaml(self, intent):
        config = SetupConfig(intent=intent, provider="openai", model="gpt-5-mini", name="test")
        content = generate_role_yaml(config)
        data = yaml.safe_load(content)
        assert data is not None
        assert "spec" in data


class TestGenerateChatYaml:
    def test_uses_run_config_schema(self):
        config = SetupConfig(intent="chatbot", provider="openai", model="gpt-5-mini")
        content = generate_run_yaml(config)
        data = yaml.safe_load(content)
        assert data["provider"] == "openai"
        assert data["model"] == "gpt-5-mini"

    def test_includes_provider_and_model(self):
        config = SetupConfig(
            intent="chatbot", provider="anthropic", model="claude-sonnet-4-5-20250929"
        )
        content = generate_run_yaml(config)
        data = yaml.safe_load(content)
        assert data["provider"] == "anthropic"
        assert data["model"] == "claude-sonnet-4-5-20250929"

    def test_includes_personality_when_set(self):
        config = SetupConfig(
            intent="chatbot",
            provider="openai",
            model="gpt-5-mini",
            personality="You are a pirate.",
        )
        content = generate_run_yaml(config)
        data = yaml.safe_load(content)
        assert data["personality"] == "You are a pirate."


class TestSaveEnvKey:
    def test_creates_directory(self, clean_env):
        result = save_env_key("TEST_KEY", "test-value")
        assert result is not None
        assert result.exists()

    def test_permissions_0o600(self, clean_env):
        import stat

        result = save_env_key("TEST_KEY", "test-value")
        assert result is not None
        mode = result.stat().st_mode
        assert stat.S_IMODE(mode) == 0o600

    def test_writes_correct_var(self, clean_env):
        result = save_env_key("MY_API_KEY", "my-secret")
        assert result is not None
        content = result.read_text()
        assert "MY_API_KEY" in content
        assert "my-secret" in content


class TestIntentTemplateMap:
    def test_all_intents_map_to_valid_template(self):
        from initrunner.templates import TEMPLATES

        for intent_key, template_key in INTENT_TEMPLATE_MAP.items():
            assert template_key in TEMPLATES, (
                f"Intent '{intent_key}' maps to template '{template_key}' which is not in TEMPLATES"
            )
