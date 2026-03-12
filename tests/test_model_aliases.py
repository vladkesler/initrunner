"""Tests for initrunner.model_aliases — alias loading, resolution, parsing."""

from __future__ import annotations

import pytest

from initrunner.model_aliases import (
    ModelAliasConfig,
    load_model_aliases,
    parse_model_string,
    resolve_model_alias,
)

# ---------------------------------------------------------------------------
# parse_model_string
# ---------------------------------------------------------------------------


class TestParseModelString:
    def test_simple(self):
        assert parse_model_string("openai:gpt-4o") == ("openai", "gpt-4o")

    def test_extra_colons(self):
        assert parse_model_string("ollama:llama3.2:latest") == ("ollama", "llama3.2:latest")

    def test_no_colon_raises(self):
        with pytest.raises(ValueError, match="expected 'provider:model'"):
            parse_model_string("gpt-4o")

    def test_empty_string_raises(self):
        with pytest.raises(ValueError, match="expected 'provider:model'"):
            parse_model_string("")


# ---------------------------------------------------------------------------
# resolve_model_alias
# ---------------------------------------------------------------------------


class TestResolveModelAlias:
    def test_with_colon_passthrough(self):
        """A value containing ':' is returned as-is (no alias lookup)."""
        result = resolve_model_alias("openai:gpt-4o", aliases={"openai:gpt-4o": "x:y"})
        assert result == "openai:gpt-4o"

    def test_known_alias(self):
        aliases = {"fast": "openai:gpt-4o-mini", "smart": "anthropic:claude-sonnet-4-20250514"}
        assert resolve_model_alias("fast", aliases=aliases) == "openai:gpt-4o-mini"

    def test_unknown_alias(self):
        """Unknown alias without colon is returned unchanged."""
        assert resolve_model_alias("unknown", aliases={}) == "unknown"

    def test_none_aliases_loads_from_disk(self, monkeypatch):
        """When aliases=None, load_model_aliases is called."""
        monkeypatch.setattr(
            "initrunner.model_aliases.load_model_aliases",
            lambda: {"local": "ollama:llama3.2"},
        )
        assert resolve_model_alias("local") == "ollama:llama3.2"


# ---------------------------------------------------------------------------
# ModelAliasConfig
# ---------------------------------------------------------------------------


class TestModelAliasConfig:
    def test_defaults(self):
        cfg = ModelAliasConfig()
        assert cfg.aliases == {}

    def test_with_aliases(self):
        cfg = ModelAliasConfig(aliases={"fast": "openai:gpt-4o-mini"})
        assert cfg.aliases["fast"] == "openai:gpt-4o-mini"


# ---------------------------------------------------------------------------
# load_model_aliases
# ---------------------------------------------------------------------------


class TestLoadModelAliases:
    def test_missing_file(self, monkeypatch, tmp_path):
        monkeypatch.setattr("initrunner.config.get_home_dir", lambda: tmp_path)
        # Clear lru_cache on get_models_config_path if it were cached
        assert load_model_aliases() == {}

    def test_valid_file(self, monkeypatch, tmp_path):
        monkeypatch.setattr("initrunner.config.get_home_dir", lambda: tmp_path)
        (tmp_path / "models.yaml").write_text(
            "aliases:\n  fast: openai:gpt-4o-mini\n  local: ollama:llama3.2:latest\n"
        )
        aliases = load_model_aliases()
        assert aliases == {"fast": "openai:gpt-4o-mini", "local": "ollama:llama3.2:latest"}

    def test_empty_file(self, monkeypatch, tmp_path):
        monkeypatch.setattr("initrunner.config.get_home_dir", lambda: tmp_path)
        (tmp_path / "models.yaml").write_text("")
        assert load_model_aliases() == {}

    def test_invalid_yaml(self, monkeypatch, tmp_path, caplog):
        monkeypatch.setattr("initrunner.config.get_home_dir", lambda: tmp_path)
        (tmp_path / "models.yaml").write_text("{{invalid yaml")
        import logging

        monkeypatch.setattr(logging.getLogger("initrunner.model_aliases"), "propagate", True)
        with caplog.at_level(logging.WARNING, logger="initrunner.model_aliases"):
            result = load_model_aliases()
        assert result == {}

    def test_alias_target_without_colon_skipped(self, monkeypatch, tmp_path, caplog):
        monkeypatch.setattr("initrunner.config.get_home_dir", lambda: tmp_path)
        (tmp_path / "models.yaml").write_text("aliases:\n  good: openai:gpt-4o\n  bad: gpt-4o\n")
        import logging

        monkeypatch.setattr(logging.getLogger("initrunner"), "propagate", True)
        with caplog.at_level(logging.WARNING, logger="initrunner.model_aliases"):
            aliases = load_model_aliases()
        assert aliases == {"good": "openai:gpt-4o"}
        assert "bad" not in aliases
        assert "must contain a ':' separator" in caplog.text

    def test_non_dict_file(self, monkeypatch, tmp_path):
        monkeypatch.setattr("initrunner.config.get_home_dir", lambda: tmp_path)
        (tmp_path / "models.yaml").write_text("- item1\n- item2\n")
        assert load_model_aliases() == {}
