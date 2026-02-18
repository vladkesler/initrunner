"""Tests for the role loader."""

import os
import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest

from initrunner.agent.loader import (
    RoleLoadError,
    _build_model,
    _load_dotenv,
    build_agent,
    load_role,
)
from initrunner.agent.schema.base import ModelConfig


@pytest.fixture
def valid_yaml(tmp_path: Path) -> Path:
    content = textwrap.dedent("""\
        apiVersion: initrunner/v1
        kind: Agent
        metadata:
          name: test-agent
          description: A test
        spec:
          role: You are helpful.
          model:
            provider: anthropic
            name: claude-sonnet-4-5-20250929
            temperature: 0.3
            max_tokens: 1024
    """)
    p = tmp_path / "role.yaml"
    p.write_text(content)
    return p


@pytest.fixture
def invalid_yaml(tmp_path: Path) -> Path:
    p = tmp_path / "bad.yaml"
    p.write_text(":\n  invalid: [yaml\n")
    return p


@pytest.fixture
def invalid_schema(tmp_path: Path) -> Path:
    content = textwrap.dedent("""\
        apiVersion: wrong/v1
        kind: Agent
        metadata:
          name: test-agent
        spec:
          role: test
          model:
            provider: x
            name: y
    """)
    p = tmp_path / "bad_schema.yaml"
    p.write_text(content)
    return p


class TestLoadRole:
    def test_valid(self, valid_yaml: Path):
        role = load_role(valid_yaml)
        assert role.metadata.name == "test-agent"
        assert role.spec.model.temperature == 0.3
        assert role.spec.model.max_tokens == 1024

    def test_file_not_found(self, tmp_path: Path):
        with pytest.raises(RoleLoadError, match="Cannot read"):
            load_role(tmp_path / "nonexistent.yaml")

    def test_invalid_yaml(self, invalid_yaml: Path):
        with pytest.raises(RoleLoadError, match="Invalid YAML"):
            load_role(invalid_yaml)

    def test_invalid_schema(self, invalid_schema: Path):
        with pytest.raises(RoleLoadError, match="Validation failed"):
            load_role(invalid_schema)

    def test_non_mapping(self, tmp_path: Path):
        p = tmp_path / "list.yaml"
        p.write_text("- item1\n- item2\n")
        with pytest.raises(RoleLoadError, match="Expected a YAML mapping"):
            load_role(p)


class TestBuildModel:
    def test_standard_provider_returns_string(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        mc = ModelConfig(provider="openai", name="gpt-5-mini")
        result = _build_model(mc)
        assert result == "openai:gpt-5-mini"

    def test_ollama_returns_openai_chat_model(self):
        from pydantic_ai.models.openai import OpenAIChatModel

        mc = ModelConfig(provider="ollama", name="llama3.2")
        result = _build_model(mc)
        assert isinstance(result, OpenAIChatModel)

    def test_ollama_default_base_url(self):
        mc = ModelConfig(provider="ollama", name="llama3.2")
        result = _build_model(mc)
        assert result.client.base_url.host == "localhost"
        assert result.client.base_url.port == 11434

    def test_ollama_custom_base_url(self):
        mc = ModelConfig(provider="ollama", name="llama3.2", base_url="http://my-server:9999/v1")
        result = _build_model(mc)
        assert "my-server" in str(result.client.base_url)

    def test_ollama_api_key(self):
        mc = ModelConfig(provider="ollama", name="llama3.2")
        result = _build_model(mc)
        assert result.client.api_key == "ollama"

    def test_custom_base_url_returns_openai_chat_model(self):
        from pydantic_ai.models.openai import OpenAIChatModel

        mc = ModelConfig(provider="openai", name="my-model", base_url="http://vllm:8000/v1")
        result = _build_model(mc)
        assert isinstance(result, OpenAIChatModel)

    def test_custom_base_url_api_key_none(self):
        """Without api_key_env, api_key=None is passed (PydanticAI resolves it)."""
        mc = ModelConfig(provider="openai", name="my-model", base_url="http://vllm:8000/v1")
        result = _build_model(mc)
        # api_key=None lets PydanticAI read OPENAI_API_KEY or use a dummy
        assert result.client.api_key != "custom-provider"

    def test_api_key_env_reads_env_var(self, monkeypatch):
        """api_key_env reads the specified env var."""
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-123")
        mc = ModelConfig(
            provider="openai",
            name="anthropic/claude-3.5-sonnet",
            base_url="https://openrouter.ai/api/v1",
            api_key_env="OPENROUTER_API_KEY",
        )
        result = _build_model(mc)
        assert result.client.api_key == "sk-or-test-123"

    def test_api_key_env_missing_raises(self, monkeypatch):
        """api_key_env with missing env var raises RoleLoadError."""
        monkeypatch.delenv("MY_CUSTOM_KEY", raising=False)
        mc = ModelConfig(
            provider="openai",
            name="some-model",
            base_url="https://custom.example.com/v1",
            api_key_env="MY_CUSTOM_KEY",
        )
        with pytest.raises(RoleLoadError, match="Environment variable 'MY_CUSTOM_KEY' is not set"):
            _build_model(mc)

    def test_docker_warning(self, tmp_path):
        """Docker warning is logged when localhost base_url inside Docker."""
        mc = ModelConfig(provider="ollama", name="llama3.2")
        with patch("initrunner.agent.loader.Path") as mock_path_cls:
            mock_path_cls.return_value.exists.return_value = True
            # Ensure it still works (warning is just logged, doesn't crash)
            result = _build_model(mc)
            assert result is not None


class TestBuildAgent:
    @patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"})
    @patch("initrunner.agent.loader.Agent")
    @patch("initrunner.agent.loader.require_provider")
    def test_agent_construction(self, mock_require, mock_agent_cls, valid_yaml: Path):
        role = load_role(valid_yaml)
        build_agent(role)
        mock_require.assert_called_once_with("anthropic")
        mock_agent_cls.assert_called_once()
        call_kwargs = mock_agent_cls.call_args
        assert call_kwargs.args[0] == "anthropic:claude-sonnet-4-5-20250929"
        assert call_kwargs.kwargs["system_prompt"] == "You are helpful."

    @patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"})
    @patch("initrunner.agent.loader.Agent")
    @patch("initrunner.agent.loader.require_provider")
    def test_output_type_default_str(self, mock_require, mock_agent_cls, valid_yaml: Path):
        role = load_role(valid_yaml)
        build_agent(role)
        call_kwargs = mock_agent_cls.call_args
        assert call_kwargs.kwargs["output_type"] is str

    @patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"})
    @patch("initrunner.agent.loader.Agent")
    @patch("initrunner.agent.loader.require_provider")
    def test_output_type_dict(self, mock_require, mock_agent_cls, valid_yaml: Path):
        role = load_role(valid_yaml)
        build_agent(role, output_type=dict)
        call_kwargs = mock_agent_cls.call_args
        assert call_kwargs.kwargs["output_type"] is dict

    @patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"})
    @patch("initrunner.agent.loader.Agent")
    @patch("initrunner.agent.loader.require_provider")
    def test_output_type_from_role_config(self, mock_require, mock_agent_cls, tmp_path: Path):
        """A role with json_schema output produces a BaseModel output_type."""
        from pydantic import BaseModel as PydanticBaseModel

        content = textwrap.dedent("""\
            apiVersion: initrunner/v1
            kind: Agent
            metadata:
              name: test-agent
              description: A test
            spec:
              role: You are helpful.
              model:
                provider: anthropic
                name: claude-sonnet-4-5-20250929
              output:
                type: json_schema
                schema:
                  type: object
                  properties:
                    status:
                      type: string
                      enum: [approved, rejected]
                    amount:
                      type: number
                  required: [status, amount]
        """)
        p = tmp_path / "role.yaml"
        p.write_text(content)
        role = load_role(p)
        build_agent(role, role_dir=tmp_path)
        call_kwargs = mock_agent_cls.call_args
        output_type = call_kwargs.kwargs["output_type"]
        assert output_type is not str
        assert issubclass(output_type, PydanticBaseModel)

    @patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"})
    @patch("initrunner.agent.loader.Agent")
    @patch("initrunner.agent.loader.require_provider")
    def test_explicit_output_type_overrides_role_config(
        self, mock_require, mock_agent_cls, tmp_path: Path
    ):
        """Explicit output_type param wins over role config."""
        content = textwrap.dedent("""\
            apiVersion: initrunner/v1
            kind: Agent
            metadata:
              name: test-agent
              description: A test
            spec:
              role: You are helpful.
              model:
                provider: anthropic
                name: claude-sonnet-4-5-20250929
              output:
                type: json_schema
                schema:
                  type: object
                  properties:
                    status:
                      type: string
                  required: [status]
        """)
        p = tmp_path / "role.yaml"
        p.write_text(content)
        role = load_role(p)
        build_agent(role, role_dir=tmp_path, output_type=dict)
        call_kwargs = mock_agent_cls.call_args
        assert call_kwargs.kwargs["output_type"] is dict

    @patch(
        "initrunner.agent.loader.require_provider",
        side_effect=RuntimeError("Provider 'anthropic' requires extra"),
    )
    def test_missing_provider_raises_role_load_error(self, mock_require, valid_yaml: Path):
        role = load_role(valid_yaml)
        with pytest.raises(RoleLoadError, match="Provider 'anthropic' requires extra"):
            build_agent(role)

    @patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"})
    @patch("initrunner.agent.loader.Agent")
    @patch("initrunner.agent.loader.require_provider")
    def test_temperature_included_for_standard_model(
        self, mock_require, mock_agent_cls, valid_yaml
    ):
        role = load_role(valid_yaml)
        build_agent(role)
        call_kwargs = mock_agent_cls.call_args
        assert "temperature" in call_kwargs.kwargs["model_settings"]

    @patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"})
    @patch("initrunner.agent.loader.Agent")
    @patch("initrunner.agent.loader.require_provider")
    def test_temperature_omitted_for_reasoning_model(self, mock_require, mock_agent_cls, tmp_path):
        content = textwrap.dedent("""\
            apiVersion: initrunner/v1
            kind: Agent
            metadata:
              name: reasoning-agent
              description: Test
            spec:
              role: You are helpful.
              model:
                provider: openai
                name: o3-mini
        """)
        p = tmp_path / "role.yaml"
        p.write_text(content)
        role = load_role(p)
        build_agent(role)
        call_kwargs = mock_agent_cls.call_args
        assert "temperature" not in call_kwargs.kwargs["model_settings"]
        assert "max_tokens" in call_kwargs.kwargs["model_settings"]


class TestApiKeyValidation:
    def test_missing_openai_key_raises(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        mc = ModelConfig(provider="openai", name="gpt-5-mini")
        with pytest.raises(RoleLoadError, match="OPENAI_API_KEY"):
            _build_model(mc)

    def test_missing_anthropic_key_raises(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        mc = ModelConfig(provider="anthropic", name="claude-sonnet-4-5-20250929")
        with pytest.raises(RoleLoadError, match="ANTHROPIC_API_KEY"):
            _build_model(mc)

    def test_set_key_passes(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test-123")
        mc = ModelConfig(provider="openai", name="gpt-5-mini")
        result = _build_model(mc)
        assert result == "openai:gpt-5-mini"

    def test_api_key_env_override_on_standard_provider(self, monkeypatch):
        """When api_key_env is set on a standard provider (no base_url), it checks that var."""
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("MY_CUSTOM_KEY", raising=False)
        mc = ModelConfig(provider="openai", name="gpt-5-mini", api_key_env="MY_CUSTOM_KEY")
        with pytest.raises(RoleLoadError, match="MY_CUSTOM_KEY"):
            _build_model(mc)

    def test_api_key_env_override_set_passes(self, monkeypatch):
        monkeypatch.setenv("MY_CUSTOM_KEY", "sk-custom")
        mc = ModelConfig(provider="openai", name="gpt-5-mini", api_key_env="MY_CUSTOM_KEY")
        result = _build_model(mc)
        assert result == "openai:gpt-5-mini"

    def test_ollama_skips_key_check(self):
        """Ollama uses custom provider path — no API key needed."""
        mc = ModelConfig(provider="ollama", name="llama3.2")
        result = _build_model(mc)
        # Ollama takes the custom provider branch, no key validation
        assert result is not None

    def test_unknown_provider_skips_key_check(self, monkeypatch):
        """Providers not in the mapping are not checked."""
        mc = ModelConfig(provider="some-new-provider", name="model-x")
        result = _build_model(mc)
        assert result == "some-new-provider:model-x"

    def test_error_message_is_actionable(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        mc = ModelConfig(provider="openai", name="gpt-5-mini")
        with pytest.raises(RoleLoadError, match="export OPENAI_API_KEY="):
            _build_model(mc)
        with pytest.raises(RoleLoadError, match=r"\.env file"):
            _build_model(mc)


class TestLoadDotenv:
    def test_local_env_file_loaded(self, tmp_path, monkeypatch):
        monkeypatch.delenv("TEST_DOTENV_VAR", raising=False)
        env_file = tmp_path / ".env"
        env_file.write_text("TEST_DOTENV_VAR=from-local-env\n")
        _load_dotenv(tmp_path)
        assert os.environ.get("TEST_DOTENV_VAR") == "from-local-env"
        # Clean up
        monkeypatch.delenv("TEST_DOTENV_VAR", raising=False)

    def test_existing_env_not_overridden(self, tmp_path, monkeypatch):
        monkeypatch.setenv("TEST_DOTENV_VAR2", "already-set")
        env_file = tmp_path / ".env"
        env_file.write_text("TEST_DOTENV_VAR2=from-file\n")
        _load_dotenv(tmp_path)
        assert os.environ.get("TEST_DOTENV_VAR2") == "already-set"

    def test_no_env_file_is_fine(self, tmp_path):
        """No .env file should not raise."""
        _load_dotenv(tmp_path)

    def test_global_env_file_loaded(self, tmp_path, monkeypatch):
        from initrunner.config import get_home_dir

        monkeypatch.delenv("TEST_GLOBAL_VAR", raising=False)
        fake_home = tmp_path / "home"
        fake_home.mkdir(parents=True)
        (fake_home / ".env").write_text("TEST_GLOBAL_VAR=from-global\n")
        monkeypatch.setenv("INITRUNNER_HOME", str(fake_home))
        get_home_dir.cache_clear()
        role_dir = tmp_path / "project"
        role_dir.mkdir()
        _load_dotenv(role_dir)
        assert os.environ.get("TEST_GLOBAL_VAR") == "from-global"
        monkeypatch.delenv("TEST_GLOBAL_VAR", raising=False)
        get_home_dir.cache_clear()

    def test_local_env_takes_precedence_over_global(self, tmp_path, monkeypatch):
        from initrunner.config import get_home_dir

        monkeypatch.delenv("TEST_PRECEDENCE_VAR", raising=False)
        fake_home = tmp_path / "home"
        fake_home.mkdir(parents=True)
        (fake_home / ".env").write_text("TEST_PRECEDENCE_VAR=global-value\n")
        monkeypatch.setenv("INITRUNNER_HOME", str(fake_home))
        get_home_dir.cache_clear()
        role_dir = tmp_path / "project"
        role_dir.mkdir()
        (role_dir / ".env").write_text("TEST_PRECEDENCE_VAR=local-value\n")
        _load_dotenv(role_dir)
        assert os.environ.get("TEST_PRECEDENCE_VAR") == "local-value"
        monkeypatch.delenv("TEST_PRECEDENCE_VAR", raising=False)
        get_home_dir.cache_clear()
