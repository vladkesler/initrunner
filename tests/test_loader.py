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
        assert role.spec.model is not None
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
    def test_standard_provider_returns_retrying_model(self, monkeypatch):
        """openai builds an explicit OpenAIResponsesModel whose httpx client
        carries the tenacity retry transport, preserving the model name."""
        from pydantic_ai.models.openai import OpenAIResponsesModel
        from pydantic_ai.retries import AsyncTenacityTransport

        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        mc = ModelConfig(provider="openai", name="gpt-5-mini")
        result = _build_model(mc)
        assert isinstance(result, OpenAIResponsesModel)
        assert result.model_name == "gpt-5-mini"
        assert result.system == "openai"
        transport = result.client._client._transport
        assert isinstance(transport, AsyncTenacityTransport)

    def test_missing_sdk_falls_back_to_string(self, monkeypatch):
        """When a provider SDK is not installed, fall back to the plain
        provider:name string so PydanticAI owns the missing-SDK error."""
        import builtins

        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name.startswith("pydantic_ai.models.anthropic") or name.startswith(
                "pydantic_ai.providers.anthropic"
            ):
                raise ImportError("anthropic SDK not installed")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        mc = ModelConfig(provider="anthropic", name="claude-sonnet-4-5-20250929")
        result = _build_model(mc)
        assert result == "anthropic:claude-sonnet-4-5-20250929"

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
        with pytest.raises(RoleLoadError, match="MY_CUSTOM_KEY"):
            _build_model(mc)

    def test_vault_key_is_injected_into_environ(self, monkeypatch, tmp_path):
        """When a standard-provider key comes from the vault, it must land in os.environ.

        OpenAI/Anthropic/Google SDKs read the key from os.environ at client
        construction time. Resolving to a local variable isn't enough.
        """
        from initrunner.credentials import reset_resolver
        from initrunner.credentials.local_vault import LocalEncryptedVault

        monkeypatch.setenv("INITRUNNER_HOME", str(tmp_path))
        from initrunner.config import get_home_dir

        get_home_dir.cache_clear()
        reset_resolver()

        vault = LocalEncryptedVault(tmp_path / "vault.enc")
        vault.init("pw")
        vault.set("OPENAI_API_KEY", "sk-from-vault")
        vault.lock()

        monkeypatch.setenv("INITRUNNER_VAULT_PASSPHRASE", "pw")
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        reset_resolver()

        mc = ModelConfig(provider="openai", name="gpt-5-mini")
        result = _build_model(mc)

        assert result.model_name == "gpt-5-mini"
        assert os.environ["OPENAI_API_KEY"] == "sk-from-vault"

    def test_shell_env_wins_over_vault(self, monkeypatch, tmp_path):
        """An exported env var must NOT be overwritten by the vault value."""
        from initrunner.credentials import reset_resolver
        from initrunner.credentials.local_vault import LocalEncryptedVault

        monkeypatch.setenv("INITRUNNER_HOME", str(tmp_path))
        from initrunner.config import get_home_dir

        get_home_dir.cache_clear()
        reset_resolver()

        vault = LocalEncryptedVault(tmp_path / "vault.enc")
        vault.init("pw")
        vault.set("OPENAI_API_KEY", "sk-from-vault")
        vault.lock()

        monkeypatch.setenv("INITRUNNER_VAULT_PASSPHRASE", "pw")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-from-shell")
        reset_resolver()

        _build_model(ModelConfig(provider="openai", name="gpt-5-mini"))
        assert os.environ["OPENAI_API_KEY"] == "sk-from-shell"

    def test_docker_warning(self, tmp_path):
        """Docker warning is logged when localhost base_url inside Docker."""
        mc = ModelConfig(provider="ollama", name="llama3.2")
        with patch("initrunner.agent.loader.Path") as mock_path_cls:
            mock_path_cls.return_value.exists.return_value = True
            # Ensure it still works (warning is just logged, doesn't crash)
            result = _build_model(mc)
            assert result is not None


class TestBuildModelFallback:
    def test_empty_fallback_returns_bare_primary(self, monkeypatch):
        """With no fallback, _build_model returns the bare primary model."""
        from pydantic_ai.models.openai import OpenAIResponsesModel

        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        mc = ModelConfig(provider="openai", name="gpt-5-mini")
        result = _build_model(mc)
        assert isinstance(result, OpenAIResponsesModel)
        assert result.model_name == "gpt-5-mini"

    def test_fallback_returns_fallback_model(self, monkeypatch):
        pytest.importorskip("anthropic")
        from pydantic_ai.models.fallback import FallbackModel

        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic")
        monkeypatch.setenv("OPENAI_API_KEY", "test-openai")
        mc = ModelConfig(
            provider="anthropic",
            name="claude-sonnet-4-5-20250929",
            fallback=["openai:gpt-4o-mini"],
        )
        result = _build_model(mc)
        assert isinstance(result, FallbackModel)

    def test_fallback_chain_walks_in_declared_order(self, monkeypatch):
        """The primary is first, fallbacks follow in the order declared."""
        pytest.importorskip("anthropic")
        pytest.importorskip("groq")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic")
        monkeypatch.setenv("OPENAI_API_KEY", "test-openai")
        monkeypatch.setenv("GROQ_API_KEY", "test-groq")
        mc = ModelConfig(
            provider="anthropic",
            name="claude-sonnet-4-5-20250929",
            fallback=["openai:gpt-4o-mini", "groq:llama-3.1-70b"],
        )
        fm = _build_model(mc)
        model_names = [m.model_name for m in fm.models]
        assert model_names[0] == "claude-sonnet-4-5-20250929"
        assert "gpt-4o-mini" in model_names[1]
        assert "llama-3.1-70b" in model_names[2]

    def test_fallback_resolves_alias_at_build_time(self, monkeypatch, tmp_path):
        pytest.importorskip("anthropic")
        from pydantic_ai.models.fallback import FallbackModel

        models_yaml = tmp_path / "models.yaml"
        models_yaml.write_text("aliases:\n  speedy: openai:gpt-4o-mini\n")
        monkeypatch.setattr("initrunner.config.get_models_config_path", lambda: models_yaml)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic")
        monkeypatch.setenv("OPENAI_API_KEY", "test-openai")
        mc = ModelConfig(
            provider="anthropic",
            name="claude-sonnet-4-5-20250929",
            fallback=["speedy"],
        )
        result = _build_model(mc)
        assert isinstance(result, FallbackModel)

    def test_fallback_missing_api_key_raises(self, monkeypatch):
        """FallbackModel builds clients eagerly; a missing key on a fallback must surface."""
        from initrunner.agent.loader import MissingApiKeyError

        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic")
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        # Clear any cached resolver so we actually see the env state.
        from initrunner.credentials import reset_resolver

        reset_resolver()
        mc = ModelConfig(
            provider="anthropic",
            name="claude-sonnet-4-5-20250929",
            fallback=["openai:gpt-4o-mini"],
        )
        with pytest.raises(MissingApiKeyError, match="OPENAI_API_KEY"):
            _build_model(mc)


class TestHttpRetryConfig:
    @staticmethod
    def _patch_capture(monkeypatch, captured):
        """Wrap the real client builder to record the retry knobs it receives."""
        from initrunner.agent import executor_retry

        real = executor_retry.build_retrying_async_client

        def fake_builder(*, attempts, max_wait):
            captured["attempts"] = attempts
            captured["max_wait"] = max_wait
            return real(attempts=attempts, max_wait=max_wait)

        monkeypatch.setattr(executor_retry, "build_retrying_async_client", fake_builder)

    def test_execution_config_threads_retry_knobs(self, monkeypatch):
        """ExecutionConfig.http_retries/http_retry_max_wait reach the client builder."""
        from initrunner.agent import loader
        from initrunner.agent.schema.execution import ExecutionConfig

        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        captured = {}
        self._patch_capture(monkeypatch, captured)
        mc = ModelConfig(provider="openai", name="gpt-5-mini")
        loader._build_model(mc, ExecutionConfig(http_retries=7, http_retry_max_wait=12.0))
        assert captured == {"attempts": 7, "max_wait": 12.0}

    def test_default_retry_knobs_when_no_execution(self, monkeypatch):
        from initrunner.agent import loader

        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        captured = {}
        self._patch_capture(monkeypatch, captured)
        loader._build_model(ModelConfig(provider="openai", name="gpt-5-mini"))
        assert captured == {"attempts": 3, "max_wait": 60.0}


class TestOverridePreservesFallback:
    def test_model_override_preserves_fallback_list(self):
        from initrunner.agent.loader import _apply_model_override
        from initrunner.agent.schema.base import ApiVersion, Kind, PartialModelConfig, RoleMetadata
        from initrunner.agent.schema.role import AgentSpec, RoleDefinition

        role = RoleDefinition(
            apiVersion=ApiVersion.V1,
            kind=Kind.AGENT,
            metadata=RoleMetadata(name="test-role"),
            spec=AgentSpec(
                role="r",
                model=PartialModelConfig(
                    provider="anthropic",
                    name="claude-sonnet-4-5-20250929",
                    fallback=["openai:gpt-4o-mini"],
                ),
            ),
        )
        overridden = _apply_model_override(role, "google", "gemini-2.5-flash")
        assert overridden.spec.model is not None
        assert overridden.spec.model.fallback == ["openai:gpt-4o-mini"]

    def test_auto_detect_preserves_fallback_from_partial(self, monkeypatch):
        from initrunner.agent.loader import resolve_role_model
        from initrunner.agent.schema.base import ApiVersion, Kind, PartialModelConfig, RoleMetadata
        from initrunner.agent.schema.role import AgentSpec, RoleDefinition

        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        role = RoleDefinition(
            apiVersion=ApiVersion.V1,
            kind=Kind.AGENT,
            metadata=RoleMetadata(name="test-role"),
            spec=AgentSpec(
                role="r",
                # Partial: no provider/name, only tuning + fallback.
                model=PartialModelConfig(
                    temperature=0.5,
                    fallback=["openai:gpt-4o-mini"],
                ),
            ),
        )
        resolved = resolve_role_model(role)
        assert resolved.spec.model is not None
        assert resolved.spec.model.fallback == ["openai:gpt-4o-mini"]
        assert resolved.spec.model.temperature == 0.5


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
        assert call_kwargs.kwargs["instructions"] == "You are helpful."

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

    @patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"})
    @patch("initrunner.agent.loader.Agent")
    @patch("initrunner.agent.loader.require_provider")
    def test_thinking_passed_to_model_settings(self, mock_require, mock_agent_cls, tmp_path):
        content = textwrap.dedent("""\
            apiVersion: initrunner/v1
            kind: Agent
            metadata:
              name: thinking-agent
              description: Test
            spec:
              role: You are helpful.
              model:
                provider: openai
                name: o3-mini
                thinking: high
        """)
        p = tmp_path / "role.yaml"
        p.write_text(content)
        role = load_role(p)
        build_agent(role)
        call_kwargs = mock_agent_cls.call_args
        assert call_kwargs.kwargs["model_settings"]["thinking"] == "high"

    @patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"})
    @patch("initrunner.agent.loader.Agent")
    @patch("initrunner.agent.loader.require_provider")
    def test_thinking_omitted_when_unset(self, mock_require, mock_agent_cls, tmp_path):
        content = textwrap.dedent("""\
            apiVersion: initrunner/v1
            kind: Agent
            metadata:
              name: plain-agent
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
        assert "thinking" not in call_kwargs.kwargs["model_settings"]

    @patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"})
    @patch("initrunner.agent.loader.Agent")
    @patch("initrunner.agent.loader.require_provider")
    def test_thinking_false_is_passed(self, mock_require, mock_agent_cls, tmp_path):
        content = textwrap.dedent("""\
            apiVersion: initrunner/v1
            kind: Agent
            metadata:
              name: no-think-agent
              description: Test
            spec:
              role: You are helpful.
              model:
                provider: openai
                name: o3-mini
                thinking: false
        """)
        p = tmp_path / "role.yaml"
        p.write_text(content)
        role = load_role(p)
        build_agent(role)
        call_kwargs = mock_agent_cls.call_args
        # Explicit disable must reach the model settings (not be dropped as falsy).
        assert call_kwargs.kwargs["model_settings"]["thinking"] is False


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
        assert result.model_name == "gpt-5-mini"

    def test_api_key_env_override_on_standard_provider(self, monkeypatch):
        """When api_key_env is set on a standard provider (no base_url), it checks that var."""
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("MY_CUSTOM_KEY", raising=False)
        mc = ModelConfig(provider="openai", name="gpt-5-mini", api_key_env="MY_CUSTOM_KEY")
        with pytest.raises(RoleLoadError, match="MY_CUSTOM_KEY"):
            _build_model(mc)

    def test_api_key_env_override_set_passes(self, monkeypatch):
        """A custom api_key_env on a standard provider is passed explicitly to
        the client -- the SDK would otherwise only read OPENAI_API_KEY."""
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.setenv("MY_CUSTOM_KEY", "sk-custom")
        from initrunner.credentials import reset_resolver

        reset_resolver()
        mc = ModelConfig(provider="openai", name="gpt-5-mini", api_key_env="MY_CUSTOM_KEY")
        result = _build_model(mc)
        assert result.model_name == "gpt-5-mini"
        # The resolved key reached the client even though OPENAI_API_KEY is unset.
        assert result.client.api_key == "sk-custom"

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


class TestAdvancedModelSettings:
    @patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"})
    @patch("initrunner.agent.loader.Agent")
    @patch("initrunner.agent.loader.require_provider")
    def test_advanced_settings_passed(self, mock_require, mock_agent_cls, tmp_path):
        content = textwrap.dedent("""\
            apiVersion: initrunner/v1
            kind: Agent
            metadata:
              name: tuned-agent
              description: Test
            spec:
              role: You are helpful.
              model:
                provider: anthropic
                name: claude-sonnet-4-5-20250929
                top_p: 0.9
                top_k: 40
                seed: 7
                stop_sequences: ["END"]
                parallel_tool_calls: false
                presence_penalty: 0.5
                frequency_penalty: -0.5
                logit_bias: {"50256": -100}
                extra_headers: {"X-Test": "1"}
                extra_body: {"route": "fast"}
                tool_choice: none
        """)
        p = tmp_path / "role.yaml"
        p.write_text(content)
        role = load_role(p)
        build_agent(role)
        settings = mock_agent_cls.call_args.kwargs["model_settings"]
        assert settings["top_p"] == 0.9
        assert settings["top_k"] == 40
        assert settings["seed"] == 7
        assert settings["stop_sequences"] == ["END"]
        assert settings["parallel_tool_calls"] is False
        assert settings["presence_penalty"] == 0.5
        assert settings["frequency_penalty"] == -0.5
        assert settings["logit_bias"] == {"50256": -100}
        assert settings["extra_headers"] == {"X-Test": "1"}
        assert settings["extra_body"] == {"route": "fast"}
        assert settings["tool_choice"] == "none"

    @patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"})
    @patch("initrunner.agent.loader.Agent")
    @patch("initrunner.agent.loader.require_provider")
    def test_unset_fields_omitted(self, mock_require, mock_agent_cls, valid_yaml):
        role = load_role(valid_yaml)
        build_agent(role)
        settings = mock_agent_cls.call_args.kwargs["model_settings"]
        for field in ("top_p", "top_k", "seed", "stop_sequences", "tool_choice"):
            assert field not in settings

    @patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"})
    @patch("initrunner.agent.loader.Agent")
    @patch("initrunner.agent.loader.require_provider")
    def test_sampling_fields_omitted_for_reasoning_model(
        self, mock_require, mock_agent_cls, tmp_path
    ):
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
                top_p: 0.9
                presence_penalty: 0.5
                seed: 7
        """)
        p = tmp_path / "role.yaml"
        p.write_text(content)
        role = load_role(p)
        build_agent(role)
        settings = mock_agent_cls.call_args.kwargs["model_settings"]
        assert "top_p" not in settings
        assert "presence_penalty" not in settings
        assert settings["seed"] == 7

    def test_tool_choice_required_rejected_with_explanation(self, tmp_path):
        content = textwrap.dedent("""\
            apiVersion: initrunner/v1
            kind: Agent
            metadata:
              name: forced-agent
              description: Test
            spec:
              role: You are helpful.
              model:
                provider: anthropic
                name: claude-sonnet-4-5-20250929
                tool_choice: required
        """)
        p = tmp_path / "role.yaml"
        p.write_text(content)
        with pytest.raises(RoleLoadError, match="dynamic capability"):
            load_role(p)


class TestPromptCache:
    @patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"})
    @patch("initrunner.agent.loader.Agent")
    @patch("initrunner.agent.loader.require_provider")
    def test_anthropic_prompt_cache_mapped(self, mock_require, mock_agent_cls, tmp_path):
        content = textwrap.dedent("""\
            apiVersion: initrunner/v1
            kind: Agent
            metadata:
              name: cached-agent
              description: Test
            spec:
              role: You are helpful.
              model:
                provider: anthropic
                name: claude-sonnet-4-5-20250929
                prompt_cache: true
        """)
        p = tmp_path / "role.yaml"
        p.write_text(content)
        build_agent(load_role(p))
        settings = mock_agent_cls.call_args.kwargs["model_settings"]
        assert settings["anthropic_cache_instructions"] == "5m"
        assert settings["anthropic_cache_tool_definitions"] == "5m"

    @patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"})
    @patch("initrunner.agent.loader.Agent")
    @patch("initrunner.agent.loader.require_provider")
    def test_structured_prompt_cache_tools_only(self, mock_require, mock_agent_cls, tmp_path):
        content = textwrap.dedent("""\
            apiVersion: initrunner/v1
            kind: Agent
            metadata:
              name: cached-agent
              description: Test
            spec:
              role: You are helpful.
              model:
                provider: anthropic
                name: claude-sonnet-4-5-20250929
                prompt_cache:
                  instructions: false
                  tools: true
                  ttl: 1h
        """)
        p = tmp_path / "role.yaml"
        p.write_text(content)
        build_agent(load_role(p))
        settings = mock_agent_cls.call_args.kwargs["model_settings"]
        assert "anthropic_cache_instructions" not in settings
        assert settings["anthropic_cache_tool_definitions"] == "1h"

    @patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"})
    @patch("initrunner.agent.loader.Agent")
    @patch("initrunner.agent.loader.require_provider")
    def test_no_cache_keys_when_unset(self, mock_require, mock_agent_cls, tmp_path):
        content = textwrap.dedent("""\
            apiVersion: initrunner/v1
            kind: Agent
            metadata:
              name: plain-agent
              description: Test
            spec:
              role: You are helpful.
              model:
                provider: anthropic
                name: claude-sonnet-4-5-20250929
        """)
        p = tmp_path / "role.yaml"
        p.write_text(content)
        build_agent(load_role(p))
        settings = mock_agent_cls.call_args.kwargs["model_settings"]
        assert not any("cache" in k for k in settings)

    def test_prompt_cache_rejected_for_openai(self, tmp_path):
        content = textwrap.dedent("""\
            apiVersion: initrunner/v1
            kind: Agent
            metadata:
              name: bad-cache
              description: Test
            spec:
              role: You are helpful.
              model:
                provider: openai
                name: gpt-4o
                prompt_cache: true
        """)
        p = tmp_path / "role.yaml"
        p.write_text(content)
        with pytest.raises(RoleLoadError, match="Anthropic and Bedrock"):
            load_role(p)


class TestFallbackOn:
    @patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"})
    def test_fallback_on_passed_to_fallback_model(self):
        import pydantic_ai.exceptions as exc
        from pydantic_ai.models.fallback import FallbackModel

        mc = ModelConfig(
            provider="openai",
            name="gpt-5-mini",
            fallback=["openai:gpt-4o-mini"],
            fallback_on=["ModelHTTPError", "ContentFilterError"],
        )
        result = _build_model(mc)
        assert isinstance(result, FallbackModel)
        # The configured exception types drive the exception handlers.
        handlers = result._exception_handlers
        assert any(
            h(exc.ModelHTTPError(status_code=500, model_name="x", body=b"")) for h in handlers
        )

    @patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"})
    def test_default_fallback_on_when_unset(self):
        from pydantic_ai.models.fallback import FallbackModel

        mc = ModelConfig(provider="openai", name="gpt-5-mini", fallback=["openai:gpt-4o-mini"])
        result = _build_model(mc)
        assert isinstance(result, FallbackModel)
        # Default is ModelAPIError; handlers exist.
        assert result._exception_handlers

    def test_fallback_on_without_fallback_rejected(self):
        import pydantic

        with pytest.raises(pydantic.ValidationError, match="no effect without fallback"):
            ModelConfig(provider="openai", name="gpt-5-mini", fallback_on=["ModelHTTPError"])

    def test_unknown_fallback_on_rejected(self):
        import pydantic

        with pytest.raises(pydantic.ValidationError, match="Unknown fallback_on"):
            ModelConfig(
                provider="openai",
                name="gpt-5-mini",
                fallback=["openai:gpt-4o-mini"],
                fallback_on=["NoSuchError"],
            )


class TestModelConcurrencyLimit:
    @pytest.fixture(autouse=True)
    def _clear_registry(self):
        from initrunner.agent.loader import _LIMITER_REGISTRY

        _LIMITER_REGISTRY.clear()
        yield
        _LIMITER_REGISTRY.clear()

    @patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"})
    def test_per_agent_limit_wraps_model(self):
        from pydantic_ai.models.concurrency import ConcurrencyLimitedModel

        mc = ModelConfig(provider="openai", name="gpt-5-mini", concurrency={"max_running": 4})
        result = _build_model(mc)
        assert isinstance(result, ConcurrencyLimitedModel)

    @patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"})
    def test_no_concurrency_not_wrapped(self):
        from pydantic_ai.models.concurrency import ConcurrencyLimitedModel

        mc = ModelConfig(provider="openai", name="gpt-5-mini")
        result = _build_model(mc)
        assert not isinstance(result, ConcurrencyLimitedModel)

    @patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"})
    def test_shared_limiter_is_same_instance(self):
        a = ModelConfig(
            provider="openai", name="gpt-5-mini", concurrency={"max_running": 3, "share": "pool"}
        )
        b = ModelConfig(
            provider="openai", name="gpt-4o-mini", concurrency={"max_running": 3, "share": "pool"}
        )
        ra = _build_model(a)
        rb = _build_model(b)
        assert ra._limiter is rb._limiter  # one shared budget across agents

    @patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"})
    def test_unnamed_limiters_are_distinct(self):
        a = ModelConfig(provider="openai", name="gpt-5-mini", concurrency={"max_running": 2})
        b = ModelConfig(provider="openai", name="gpt-5-mini", concurrency={"max_running": 2})
        ra = _build_model(a)
        rb = _build_model(b)
        assert ra._limiter is not rb._limiter  # per-agent, not shared

    @patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"})
    def test_concurrency_with_fallback(self):
        from pydantic_ai.models.concurrency import ConcurrencyLimitedModel

        mc = ModelConfig(
            provider="openai",
            name="gpt-5-mini",
            fallback=["openai:gpt-4o-mini"],
            concurrency={"max_running": 2},
        )
        result = _build_model(mc)
        assert isinstance(result, ConcurrencyLimitedModel)
