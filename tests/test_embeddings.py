"""Tests for the embeddings module: api_key_env and compute_model_identity."""

from unittest.mock import MagicMock, patch

import pytest

from initrunner.ingestion.embeddings import (
    _PROVIDER_EMBEDDING_KEY_DEFAULTS,
    _default_embedding_key_env,
    compute_model_identity,
)


class TestApiKeyEnv:
    def test_custom_embedder_uses_api_key_env(self, monkeypatch):
        """When api_key_env is set, the env var value should be used as api_key."""
        monkeypatch.setenv("MY_EMBED_KEY", "secret-key-123")
        mock_provider = MagicMock()
        with (
            patch(
                "pydantic_ai.providers.openai.OpenAIProvider",
                return_value=mock_provider,
            ) as mock_cls,
            patch("initrunner.ingestion.embeddings.Embedder", return_value=MagicMock()),
        ):
            from initrunner.ingestion.embeddings import _create_custom_embedder

            _create_custom_embedder(
                "custom", "my-model", "http://server/v1", api_key_env="MY_EMBED_KEY"
            )
            mock_cls.assert_called_once_with(base_url="http://server/v1", api_key="secret-key-123")

    def test_custom_embedder_fallback_without_api_key_env(self):
        """When api_key_env is empty, fallback to 'custom-provider'."""
        mock_provider = MagicMock()
        with (
            patch(
                "pydantic_ai.providers.openai.OpenAIProvider",
                return_value=mock_provider,
            ) as mock_cls,
            patch("initrunner.ingestion.embeddings.Embedder", return_value=MagicMock()),
        ):
            from initrunner.ingestion.embeddings import _create_custom_embedder

            _create_custom_embedder("custom", "my-model", "http://server/v1", api_key_env="")
            mock_cls.assert_called_once_with(base_url="http://server/v1", api_key="custom-provider")

    def test_custom_embedder_missing_env_var_raises(self, monkeypatch):
        """When api_key_env names a missing env var, raise ValueError."""
        monkeypatch.delenv("NONEXISTENT_KEY", raising=False)
        from initrunner.ingestion.embeddings import _create_custom_embedder

        with pytest.raises(ValueError, match=r"NONEXISTENT_KEY.*missing or empty"):
            _create_custom_embedder(
                "custom", "my-model", "http://server/v1", api_key_env="NONEXISTENT_KEY"
            )

    def test_create_embedder_passes_api_key_env_to_custom(self, monkeypatch):
        """create_embedder should forward api_key_env to _create_custom_embedder."""
        monkeypatch.setenv("MY_KEY", "key-val")
        mock_provider = MagicMock()
        with (
            patch(
                "pydantic_ai.providers.openai.OpenAIProvider",
                return_value=mock_provider,
            ) as mock_cls,
            patch("initrunner.ingestion.embeddings.Embedder", return_value=MagicMock()),
        ):
            from initrunner.ingestion.embeddings import create_embedder

            create_embedder(
                provider="custom",
                model="my-model",
                base_url="http://server/v1",
                api_key_env="MY_KEY",
            )
            mock_cls.assert_called_once_with(base_url="http://server/v1", api_key="key-val")

    def test_ollama_ignores_api_key_env(self):
        """Ollama provider always uses 'ollama' as api_key regardless of api_key_env."""
        mock_provider = MagicMock()
        with (
            patch(
                "pydantic_ai.providers.openai.OpenAIProvider",
                return_value=mock_provider,
            ) as mock_cls,
            patch("initrunner.ingestion.embeddings.Embedder", return_value=MagicMock()),
        ):
            from initrunner.ingestion.embeddings import _create_custom_embedder

            _create_custom_embedder("ollama", "nomic-embed-text", "", api_key_env="SOME_KEY")
            mock_cls.assert_called_once_with(base_url="http://localhost:11434/v1", api_key="ollama")


class TestComputeModelIdentity:
    def test_standard_openai(self):
        result = compute_model_identity("openai", "text-embedding-3-small")
        assert result == "openai:text-embedding-3-small"

    def test_standard_google(self):
        result = compute_model_identity("google", "text-embedding-004")
        assert result == "google:text-embedding-004"

    def test_model_with_provider_prefix(self):
        result = compute_model_identity("openai", "openai:text-embedding-3-large")
        assert result == "openai:text-embedding-3-large"

    def test_default_model_when_empty(self):
        result = compute_model_identity("openai", "")
        assert result == "openai:text-embedding-3-small"

    def test_custom_with_base_url(self):
        result = compute_model_identity("custom", "my-model", "http://server:8000/v1")
        assert (
            result
            == "custom:my-model:"
            + __import__("hashlib").sha256(b"http://server:8000/v1").hexdigest()[:8]
        )

    def test_different_urls_produce_different_identities(self):
        id1 = compute_model_identity("custom", "model", "http://server1/v1")
        id2 = compute_model_identity("custom", "model", "http://server2/v1")
        assert id1 != id2

    def test_same_url_produces_same_identity(self):
        id1 = compute_model_identity("custom", "model", "http://server/v1")
        id2 = compute_model_identity("custom", "model", "http://server/v1")
        assert id1 == id2

    def test_no_base_url_no_hash(self):
        result = compute_model_identity("openai", "text-embedding-3-small", "")
        assert ":" in result
        parts = result.split(":")
        assert len(parts) == 2  # provider:model, no hash


class TestProviderEmbeddingKeyDefaults:
    """Tests for the provider-to-embedding-key mapping and helper."""

    def test_openai_default_key(self):
        assert _default_embedding_key_env("openai") == "OPENAI_API_KEY"

    def test_anthropic_default_key(self):
        assert _default_embedding_key_env("anthropic") == "OPENAI_API_KEY"

    def test_google_default_key(self):
        assert _default_embedding_key_env("google") == "GOOGLE_API_KEY"

    def test_unknown_provider_falls_back_to_openai(self):
        assert _default_embedding_key_env("unknown") == "OPENAI_API_KEY"

    def test_mapping_has_expected_providers(self):
        assert "openai" in _PROVIDER_EMBEDDING_KEY_DEFAULTS
        assert "anthropic" in _PROVIDER_EMBEDDING_KEY_DEFAULTS
        assert "google" in _PROVIDER_EMBEDDING_KEY_DEFAULTS


class TestStandardProviderApiKeyEnv:
    """Tests for api_key_env support on standard (non-custom, non-ollama) providers."""

    def test_openai_standard_uses_explicit_key(self, monkeypatch):
        """OpenAI standard provider should construct with explicit API key."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test-123")
        mock_openai_model = MagicMock()
        mock_provider = MagicMock()
        with (
            patch(
                "pydantic_ai.embeddings.openai.OpenAIEmbeddingModel",
                return_value=mock_openai_model,
            ) as mock_model_cls,
            patch(
                "pydantic_ai.providers.openai.OpenAIProvider",
                return_value=mock_provider,
            ) as mock_prov_cls,
            patch("initrunner.ingestion.embeddings.Embedder", return_value=MagicMock()) as mock_emb,
        ):
            from initrunner.ingestion.embeddings import create_embedder

            create_embedder(provider="openai")
            mock_prov_cls.assert_called_once_with(api_key="sk-test-123")
            mock_model_cls.assert_called_once_with("text-embedding-3-small", provider=mock_provider)
            mock_emb.assert_called_once_with(mock_openai_model)

    def test_anthropic_standard_requires_openai_key(self, monkeypatch):
        """Anthropic uses OpenAI for embeddings — OPENAI_API_KEY must be set."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-embed-key")
        mock_openai_model = MagicMock()
        mock_provider = MagicMock()
        with (
            patch(
                "pydantic_ai.embeddings.openai.OpenAIEmbeddingModel",
                return_value=mock_openai_model,
            ),
            patch(
                "pydantic_ai.providers.openai.OpenAIProvider",
                return_value=mock_provider,
            ) as mock_prov_cls,
            patch("initrunner.ingestion.embeddings.Embedder", return_value=MagicMock()),
        ):
            from initrunner.ingestion.embeddings import create_embedder

            create_embedder(provider="anthropic")
            mock_prov_cls.assert_called_once_with(api_key="sk-embed-key")

    def test_google_standard_uses_google_key(self, monkeypatch):
        """Google provider should call _create_standard_embedder with correct key."""
        monkeypatch.setenv("GOOGLE_API_KEY", "goog-key-123")
        mock_embedder = MagicMock()
        with patch(
            "initrunner.ingestion.embeddings._create_standard_embedder",
            return_value=mock_embedder,
        ) as mock_create:
            from initrunner.ingestion.embeddings import create_embedder

            result = create_embedder(provider="google")
            mock_create.assert_called_once_with(
                "google", "google:text-embedding-004", "goog-key-123"
            )
            assert result is mock_embedder

    def test_standard_provider_custom_api_key_env(self, monkeypatch):
        """api_key_env override should be honored for standard providers."""
        monkeypatch.setenv("MY_CUSTOM_KEY", "custom-val")
        mock_openai_model = MagicMock()
        mock_provider = MagicMock()
        with (
            patch(
                "pydantic_ai.embeddings.openai.OpenAIEmbeddingModel",
                return_value=mock_openai_model,
            ),
            patch(
                "pydantic_ai.providers.openai.OpenAIProvider",
                return_value=mock_provider,
            ) as mock_prov_cls,
            patch("initrunner.ingestion.embeddings.Embedder", return_value=MagicMock()),
        ):
            from initrunner.ingestion.embeddings import create_embedder

            create_embedder(provider="openai", api_key_env="MY_CUSTOM_KEY")
            mock_prov_cls.assert_called_once_with(api_key="custom-val")

    def test_missing_openai_key_raises_for_openai(self, monkeypatch):
        """Missing OPENAI_API_KEY for openai provider raises clear ValueError."""
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        from initrunner.ingestion.embeddings import create_embedder

        with pytest.raises(ValueError, match=r"OPENAI_API_KEY"):
            create_embedder(provider="openai")

    def test_missing_openai_key_raises_for_anthropic(self, monkeypatch):
        """Missing OPENAI_API_KEY for anthropic provider raises clear ValueError with hint."""
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        from initrunner.ingestion.embeddings import create_embedder

        with pytest.raises(ValueError, match=r"Anthropic has no embeddings API"):
            create_embedder(provider="anthropic")

    def test_missing_google_key_raises_for_google(self, monkeypatch):
        """Missing GOOGLE_API_KEY for google provider raises clear ValueError."""
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        from initrunner.ingestion.embeddings import create_embedder

        with pytest.raises(ValueError, match=r"GOOGLE_API_KEY"):
            create_embedder(provider="google")

    def test_missing_custom_api_key_env_raises(self, monkeypatch):
        """Missing env var specified via api_key_env raises ValueError."""
        monkeypatch.delenv("MY_MISSING_KEY", raising=False)
        from initrunner.ingestion.embeddings import create_embedder

        with pytest.raises(ValueError, match=r"MY_MISSING_KEY"):
            create_embedder(provider="openai", api_key_env="MY_MISSING_KEY")

    def test_error_message_mentions_override(self, monkeypatch):
        """Error message should mention ingest.embeddings.api_key_env override."""
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        from initrunner.ingestion.embeddings import create_embedder

        with pytest.raises(ValueError, match=r"ingest\.embeddings\.api_key_env"):
            create_embedder(provider="openai")
