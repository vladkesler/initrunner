"""Tests for the embeddings module: api_key_env and compute_model_identity."""

from unittest.mock import MagicMock, patch

import pytest

from initrunner.ingestion.embeddings import compute_model_identity


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
