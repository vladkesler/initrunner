"""Tests for default model detection, save, and clear."""

from __future__ import annotations

from unittest.mock import patch

import pytest
import yaml


class TestDetectDefaultModel:
    """Tests for detect_default_model() source precedence."""

    def test_initrunner_model_env_wins(self, monkeypatch):
        monkeypatch.setenv("INITRUNNER_MODEL", "anthropic:claude-sonnet-4-5-20250929")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

        from initrunner.agent.loader import detect_default_model

        prov, name, _url, _key, source = detect_default_model()
        assert source == "initrunner_model_env"
        assert prov == "anthropic"
        assert name == "claude-sonnet-4-5-20250929"

    def test_run_yaml_beats_env_detection(self, monkeypatch, tmp_path):
        monkeypatch.delenv("INITRUNNER_MODEL", raising=False)
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

        home = tmp_path / "home"
        home.mkdir()
        (home / "run.yaml").write_text(
            "provider: openai\nmodel: google/gemini-3-flash\n"
            "base_url: https://openrouter.ai/api/v1\n"
            "api_key_env: OPENROUTER_API_KEY\n"
        )
        monkeypatch.setenv("INITRUNNER_HOME", str(home))
        from initrunner.config import get_home_dir

        get_home_dir.cache_clear()

        from initrunner.agent.loader import detect_default_model

        prov, name, base_url, api_key_env, source = detect_default_model()
        assert source == "run_yaml"
        assert prov == "openai"
        assert name == "google/gemini-3-flash"
        assert base_url == "https://openrouter.ai/api/v1"
        assert api_key_env == "OPENROUTER_API_KEY"

    def test_auto_detected_from_api_key(self, monkeypatch, tmp_path):
        monkeypatch.delenv("INITRUNNER_MODEL", raising=False)
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setenv("INITRUNNER_HOME", str(home))
        from initrunner.config import get_home_dir

        get_home_dir.cache_clear()

        from initrunner.agent.loader import detect_default_model

        prov, _name, _url, _key, source = detect_default_model()
        assert source in ("auto_detected", "run_yaml")
        assert prov != ""

    def test_none_when_nothing_configured(self, monkeypatch, tmp_path):
        for key in (
            "OPENAI_API_KEY",
            "ANTHROPIC_API_KEY",
            "GOOGLE_API_KEY",
            "GROQ_API_KEY",
            "MISTRAL_API_KEY",
            "CO_API_KEY",
            "XAI_API_KEY",
            "INITRUNNER_MODEL",
        ):
            monkeypatch.delenv(key, raising=False)
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setenv("INITRUNNER_HOME", str(home))
        from initrunner.config import get_home_dir

        get_home_dir.cache_clear()

        from initrunner.agent.loader import detect_default_model

        with patch("initrunner.services.providers._is_ollama_running", return_value=False):
            prov, name, _url, _key, source = detect_default_model()
        assert source == "none"
        assert prov == ""
        assert name == ""


class TestSaveRunConfig:
    def test_preserves_non_model_fields(self, monkeypatch, tmp_path):
        home = tmp_path / "home"
        home.mkdir()
        (home / "run.yaml").write_text(
            "provider: openai\nmodel: gpt-5-mini\n"
            "tool_profile: all\nmemory: true\npersonality: friendly\n"
        )
        monkeypatch.setenv("INITRUNNER_HOME", str(home))
        from initrunner.config import get_home_dir

        get_home_dir.cache_clear()

        from initrunner.cli.run_config import save_run_config

        save_run_config("anthropic", "claude-sonnet-4-5-20250929")

        data = yaml.safe_load((home / "run.yaml").read_text())
        assert data["provider"] == "anthropic"
        assert data["model"] == "claude-sonnet-4-5-20250929"
        assert data["tool_profile"] == "all"
        assert data["memory"] is True
        assert data["personality"] == "friendly"

    def test_writes_base_url_and_api_key_env(self, monkeypatch, tmp_path):
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setenv("INITRUNNER_HOME", str(home))
        from initrunner.config import get_home_dir

        get_home_dir.cache_clear()

        from initrunner.cli.run_config import save_run_config

        save_run_config(
            "openai",
            "google/gemini-3-flash",
            base_url="https://openrouter.ai/api/v1",
            api_key_env="OPENROUTER_API_KEY",
        )

        data = yaml.safe_load((home / "run.yaml").read_text())
        assert data["base_url"] == "https://openrouter.ai/api/v1"
        assert data["api_key_env"] == "OPENROUTER_API_KEY"


class TestClearRunConfigModel:
    def test_clears_only_model_fields(self, monkeypatch, tmp_path):
        home = tmp_path / "home"
        home.mkdir()
        (home / "run.yaml").write_text(
            "provider: openai\nmodel: gpt-5-mini\n"
            "base_url: https://example.com\napi_key_env: MY_KEY\n"
            "tool_profile: all\nmemory: false\n"
        )
        monkeypatch.setenv("INITRUNNER_HOME", str(home))
        from initrunner.config import get_home_dir

        get_home_dir.cache_clear()

        from initrunner.cli.run_config import clear_run_config_model

        clear_run_config_model()

        data = yaml.safe_load((home / "run.yaml").read_text())
        assert "provider" not in data
        assert "model" not in data
        assert "base_url" not in data
        assert "api_key_env" not in data
        assert data["tool_profile"] == "all"
        assert data["memory"] is False


class TestSystemEndpoints:
    """Integration tests for /api/system/default-model endpoints."""

    @pytest.fixture
    def app(self):
        from initrunner.dashboard.app import create_app
        from initrunner.dashboard.config import DashboardSettings

        return create_app(DashboardSettings())

    @pytest.fixture
    def client(self, app):
        from starlette.testclient import TestClient

        return TestClient(app, raise_server_exceptions=False)

    def test_get_default_model(self, client):
        resp = client.get("/api/system/default-model")
        assert resp.status_code == 200
        data = resp.json()
        assert "source" in data
        assert data["source"] in ("initrunner_model_env", "run_yaml", "auto_detected", "none")

    def test_save_normalizes_preset(self, client, monkeypatch, tmp_path):
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setenv("INITRUNNER_HOME", str(home))
        from initrunner.config import get_home_dir

        get_home_dir.cache_clear()

        resp = client.post(
            "/api/system/default-model",
            json={"provider": "openrouter", "model": "google/gemini-3-flash"},
        )
        assert resp.status_code == 200
        data = resp.json()
        # OpenRouter normalized to canonical openai + base_url
        assert data["provider"] == "openai"
        assert data["base_url"] == "https://openrouter.ai/api/v1"
        assert data["source"] == "run_yaml"

    def test_delete_resets(self, client, monkeypatch, tmp_path):
        home = tmp_path / "home"
        home.mkdir()
        (home / "run.yaml").write_text("provider: openai\nmodel: gpt-5-mini\n")
        monkeypatch.setenv("INITRUNNER_HOME", str(home))
        from initrunner.config import get_home_dir

        get_home_dir.cache_clear()

        resp = client.delete("/api/system/default-model")
        assert resp.status_code == 200
        data = resp.json()
        # After clear, source should no longer be run_yaml
        assert data["source"] != "run_yaml"
