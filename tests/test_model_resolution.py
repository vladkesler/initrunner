"""Tests for model auto-resolution when spec.model is omitted or partial."""

import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest

from initrunner.agent.loader import RoleLoadError, load_role, resolve_role_model
from initrunner.agent.schema.base import ModelConfig, PartialModelConfig


@pytest.fixture
def no_model_yaml(tmp_path: Path) -> Path:
    content = textwrap.dedent("""\
        apiVersion: initrunner/v1
        kind: Agent
        metadata:
          name: test-no-model
        spec:
          role: You are helpful.
    """)
    p = tmp_path / "role.yaml"
    p.write_text(content)
    return p


@pytest.fixture
def partial_model_yaml(tmp_path: Path) -> Path:
    content = textwrap.dedent("""\
        apiVersion: initrunner/v1
        kind: Agent
        metadata:
          name: test-partial
        spec:
          role: You are helpful.
          model:
            temperature: 0.3
            max_tokens: 2048
    """)
    p = tmp_path / "role.yaml"
    p.write_text(content)
    return p


@pytest.fixture
def full_model_yaml(tmp_path: Path) -> Path:
    content = textwrap.dedent("""\
        apiVersion: initrunner/v1
        kind: Agent
        metadata:
          name: test-full
        spec:
          role: You are helpful.
          model:
            provider: anthropic
            name: claude-sonnet-4-5-20250929
            temperature: 0.5
    """)
    p = tmp_path / "role.yaml"
    p.write_text(content)
    return p


class TestPartialModelConfig:
    def test_empty_is_not_resolved(self):
        p = PartialModelConfig()
        assert not p.is_resolved()

    def test_name_only_is_not_resolved(self):
        p = PartialModelConfig(name="gpt-5-mini")
        assert not p.is_resolved()

    def test_provider_and_name_is_resolved(self):
        p = PartialModelConfig(provider="openai", name="gpt-5-mini")
        assert p.is_resolved()

    def test_tuning_only_is_not_resolved(self):
        p = PartialModelConfig(temperature=0.3, max_tokens=2048)
        assert not p.is_resolved()


class TestLoadRoleWithOptionalModel:
    def test_no_model_loads_as_none(self, no_model_yaml: Path):
        role = load_role(no_model_yaml)
        assert role.spec.model is None

    def test_partial_model_loads_unresolved(self, partial_model_yaml: Path):
        role = load_role(partial_model_yaml)
        assert role.spec.model is not None
        assert not role.spec.model.is_resolved()
        assert role.spec.model.temperature == 0.3
        assert role.spec.model.max_tokens == 2048

    def test_full_model_loads_resolved(self, full_model_yaml: Path):
        role = load_role(full_model_yaml)
        assert role.spec.model is not None
        assert role.spec.model.is_resolved()
        assert role.spec.model.provider == "anthropic"


class TestResolveRoleModel:
    def test_override_wins(self, no_model_yaml: Path):
        role = load_role(no_model_yaml)
        resolved = resolve_role_model(role, no_model_yaml, model_override="openai:gpt-5-mini")
        assert isinstance(resolved.spec.model, ModelConfig)
        assert resolved.spec.model.provider == "openai"
        assert resolved.spec.model.name == "gpt-5-mini"

    def test_override_preserves_tuning(self, partial_model_yaml: Path):
        role = load_role(partial_model_yaml)
        resolved = resolve_role_model(role, partial_model_yaml, model_override="openai:gpt-5-mini")
        assert resolved.spec.model.name == "gpt-5-mini"
        assert resolved.spec.model.temperature == 0.3
        assert resolved.spec.model.max_tokens == 2048

    def test_full_model_passes_through(self, full_model_yaml: Path):
        role = load_role(full_model_yaml)
        resolved = resolve_role_model(role, full_model_yaml)
        assert isinstance(resolved.spec.model, ModelConfig)
        assert resolved.spec.model.provider == "anthropic"
        assert resolved.spec.model.temperature == 0.5

    def test_env_var_auto_detect(self, no_model_yaml: Path, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        monkeypatch.delenv("INITRUNNER_MODEL", raising=False)
        role = load_role(no_model_yaml)
        resolved = resolve_role_model(role, no_model_yaml)
        assert isinstance(resolved.spec.model, ModelConfig)
        assert resolved.spec.model.provider == "openai"
        assert resolved.spec.model.name  # some default model name

    def test_initrunner_model_env_beats_detection(self, no_model_yaml: Path, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        monkeypatch.setenv("INITRUNNER_MODEL", "anthropic:claude-sonnet-4-5-20250929")
        role = load_role(no_model_yaml)
        resolved = resolve_role_model(role, no_model_yaml)
        assert resolved.spec.model.provider == "anthropic"
        assert resolved.spec.model.name == "claude-sonnet-4-5-20250929"

    def test_partial_merges_with_auto_detect(self, partial_model_yaml: Path, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        monkeypatch.delenv("INITRUNNER_MODEL", raising=False)
        role = load_role(partial_model_yaml)
        resolved = resolve_role_model(role, partial_model_yaml)
        assert isinstance(resolved.spec.model, ModelConfig)
        assert resolved.spec.model.provider == "openai"
        assert resolved.spec.model.temperature == 0.3
        assert resolved.spec.model.max_tokens == 2048

    def test_no_provider_raises(self, no_model_yaml: Path, monkeypatch):
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
        home = no_model_yaml.parent / "home"
        home.mkdir(exist_ok=True)
        monkeypatch.setenv("INITRUNNER_HOME", str(home))

        from initrunner.config import get_home_dir

        get_home_dir.cache_clear()

        role = load_role(no_model_yaml)
        with patch("initrunner.services.providers._is_ollama_running", return_value=False):
            with pytest.raises(RoleLoadError, match="No model specified"):
                resolve_role_model(role, no_model_yaml)

    def test_run_yaml_detection(self, no_model_yaml: Path, monkeypatch, tmp_path):
        """run.yaml from setup provides provider/model/base_url."""
        home = tmp_path / "home"
        home.mkdir()
        (home / "run.yaml").write_text(
            "provider: openai\n"
            "model: google/gemini-3-flash-preview\n"
            "base_url: https://openrouter.ai/api/v1\n"
            "api_key_env: OPENROUTER_API_KEY\n"
        )
        monkeypatch.setenv("INITRUNNER_HOME", str(home))
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("INITRUNNER_MODEL", raising=False)

        from initrunner.config import get_home_dir

        get_home_dir.cache_clear()

        role = load_role(no_model_yaml)
        resolved = resolve_role_model(role, no_model_yaml)
        assert resolved.spec.model.provider == "openai"
        assert resolved.spec.model.name == "google/gemini-3-flash-preview"
        assert resolved.spec.model.base_url == "https://openrouter.ai/api/v1"
        assert resolved.spec.model.api_key_env == "OPENROUTER_API_KEY"
