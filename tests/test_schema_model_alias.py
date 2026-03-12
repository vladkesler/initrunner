"""Tests for ModelConfig alias resolution in role YAML parsing."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from initrunner.agent.schema.base import ModelConfig


class TestModelConfigAliasResolution:
    """Path A: alias resolution inside ModelConfig validators."""

    def test_explicit_provider_no_resolution(self, monkeypatch):
        """When provider is set, alias resolution is skipped."""
        monkeypatch.setattr(
            "initrunner.model_aliases.load_model_aliases",
            lambda: {"fast": "openai:gpt-4o-mini"},
        )
        cfg = ModelConfig(provider="openai", name="fast")
        assert cfg.provider == "openai"
        assert cfg.name == "fast"  # NOT resolved — provider was explicit

    def test_inline_provider_model(self):
        """name='openai:gpt-4o' with no provider splits on colon."""
        cfg = ModelConfig(name="openai:gpt-4o")
        assert cfg.provider == "openai"
        assert cfg.name == "gpt-4o"

    def test_inline_with_extra_colons(self):
        """name='ollama:llama3.2:latest' splits on first colon."""
        cfg = ModelConfig(name="ollama:llama3.2:latest")
        assert cfg.provider == "ollama"
        assert cfg.name == "llama3.2:latest"

    def test_alias_resolved(self, monkeypatch):
        """name='fast' with no provider resolves via alias map."""
        monkeypatch.setattr(
            "initrunner.model_aliases.load_model_aliases",
            lambda: {"fast": "openai:gpt-4o-mini"},
        )
        cfg = ModelConfig(name="fast")
        assert cfg.provider == "openai"
        assert cfg.name == "gpt-4o-mini"

    def test_alias_with_extra_colons(self, monkeypatch):
        """Alias target 'ollama:llama3.2:latest' splits correctly."""
        monkeypatch.setattr(
            "initrunner.model_aliases.load_model_aliases",
            lambda: {"local": "ollama:llama3.2:latest"},
        )
        cfg = ModelConfig(name="local")
        assert cfg.provider == "ollama"
        assert cfg.name == "llama3.2:latest"

    def test_unresolved_alias_raises(self, monkeypatch):
        """name='nonexistent' with no provider raises ValueError."""
        monkeypatch.setattr(
            "initrunner.model_aliases.load_model_aliases",
            lambda: {},
        )
        with pytest.raises(ValidationError, match="Could not resolve provider"):
            ModelConfig(name="nonexistent")

    def test_dict_input(self, monkeypatch):
        """Pydantic dict input also triggers resolution."""
        monkeypatch.setattr(
            "initrunner.model_aliases.load_model_aliases",
            lambda: {"smart": "anthropic:claude-sonnet-4-20250514"},
        )
        cfg = ModelConfig.model_validate({"name": "smart"})
        assert cfg.provider == "anthropic"
        assert cfg.name == "claude-sonnet-4-20250514"

    def test_empty_provider_string_triggers_resolution(self, monkeypatch):
        """Explicit provider='' triggers resolution."""
        monkeypatch.setattr(
            "initrunner.model_aliases.load_model_aliases",
            lambda: {"fast": "openai:gpt-4o-mini"},
        )
        cfg = ModelConfig(provider="", name="fast")
        assert cfg.provider == "openai"
        assert cfg.name == "gpt-4o-mini"

    def test_preserves_temperature_and_max_tokens(self, monkeypatch):
        """Resolution preserves other fields."""
        monkeypatch.setattr(
            "initrunner.model_aliases.load_model_aliases",
            lambda: {"fast": "openai:gpt-4o-mini"},
        )
        cfg = ModelConfig(name="fast", temperature=0.7, max_tokens=2048)
        assert cfg.temperature == 0.7
        assert cfg.max_tokens == 2048
        assert cfg.provider == "openai"
