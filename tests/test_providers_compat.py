"""Tests for provider compatibility checking."""

import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest

from initrunner.services.providers import (
    check_role_provider_compatibility,
    list_available_providers,
)

ROLE_OPENAI = textwrap.dedent("""\
    apiVersion: initrunner/v1
    kind: Agent
    metadata:
      name: test-agent
    spec:
      role: You are helpful.
      model:
        provider: openai
        name: gpt-5-mini
""")

ROLE_ANTHROPIC_WITH_RAG = textwrap.dedent("""\
    apiVersion: initrunner/v1
    kind: Agent
    metadata:
      name: rag-agent
    spec:
      role: You answer from documents.
      model:
        provider: anthropic
        name: claude-sonnet-4-5-20250929
      ingest:
        sources:
          - "./docs/**/*.md"
""")

ROLE_WITH_EXPLICIT_EMBEDDINGS = textwrap.dedent("""\
    apiVersion: initrunner/v1
    kind: Agent
    metadata:
      name: custom-emb-agent
    spec:
      role: You answer from documents.
      model:
        provider: anthropic
        name: claude-sonnet-4-5-20250929
      ingest:
        sources:
          - "./docs/**/*.md"
        embeddings:
          provider: google
          model: text-embedding-004
""")

ROLE_WITH_MEMORY = textwrap.dedent("""\
    apiVersion: initrunner/v1
    kind: Agent
    metadata:
      name: memory-agent
    spec:
      role: You remember things.
      model:
        provider: groq
        name: llama-3.3-70b-versatile
      memory:
        semantic:
          max_memories: 500
""")

ROLE_OLLAMA = textwrap.dedent("""\
    apiVersion: initrunner/v1
    kind: Agent
    metadata:
      name: local-agent
    spec:
      role: You are local.
      model:
        provider: ollama
        name: llama3.2
""")


@pytest.fixture()
def role_file(tmp_path):
    """Write a role YAML and return its path."""

    def _write(content: str) -> Path:
        p = tmp_path / "role.yaml"
        p.write_text(content)
        return p

    return _write


def _noop_load_env():
    """No-op replacement for _load_env to prevent dotenv side effects."""


class TestListAvailableProviders:
    def test_single_provider(self, monkeypatch):
        monkeypatch.setattr("initrunner.services.providers._load_env", _noop_load_env)
        monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
        monkeypatch.delenv("CO_API_KEY", raising=False)
        monkeypatch.delenv("XAI_API_KEY", raising=False)
        with patch("initrunner.services.providers._is_ollama_running", return_value=False):
            result = list_available_providers()
        assert len(result) == 1
        assert result[0].provider == "groq"

    def test_multiple_providers(self, monkeypatch):
        monkeypatch.setattr("initrunner.services.providers._load_env", _noop_load_env)
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        monkeypatch.delenv("GROQ_API_KEY", raising=False)
        monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
        monkeypatch.delenv("CO_API_KEY", raising=False)
        monkeypatch.delenv("XAI_API_KEY", raising=False)
        with patch("initrunner.services.providers._is_ollama_running", return_value=False):
            result = list_available_providers()
        providers = [r.provider for r in result]
        assert "anthropic" in providers
        assert "openai" in providers

    def test_ollama_included_when_running(self, monkeypatch):
        monkeypatch.setattr("initrunner.services.providers._load_env", _noop_load_env)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        monkeypatch.delenv("GROQ_API_KEY", raising=False)
        monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
        monkeypatch.delenv("CO_API_KEY", raising=False)
        monkeypatch.delenv("XAI_API_KEY", raising=False)
        with (
            patch("initrunner.services.providers._is_ollama_running", return_value=True),
            patch(
                "initrunner.services.providers._get_first_ollama_model",
                return_value="deepseek-coder",
            ),
        ):
            result = list_available_providers()
        assert len(result) == 1
        assert result[0].provider == "ollama"
        assert result[0].model == "deepseek-coder"

    def test_no_providers(self, monkeypatch):
        monkeypatch.setattr("initrunner.services.providers._load_env", _noop_load_env)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        monkeypatch.delenv("GROQ_API_KEY", raising=False)
        monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
        monkeypatch.delenv("CO_API_KEY", raising=False)
        monkeypatch.delenv("XAI_API_KEY", raising=False)
        with patch("initrunner.services.providers._is_ollama_running", return_value=False):
            result = list_available_providers()
        assert result == []


class TestCheckRoleProviderCompatibility:
    @pytest.fixture(autouse=True)
    def _no_load_env(self, monkeypatch):
        monkeypatch.setattr("initrunner.services.providers._load_env", _noop_load_env)

    def test_matching_provider(self, role_file, monkeypatch):
        """User has the key the role needs."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        with patch("initrunner.services.providers._is_ollama_running", return_value=False):
            compat = check_role_provider_compatibility(role_file(ROLE_OPENAI))
        assert compat.role_provider == "openai"
        assert compat.user_has_key is True
        assert compat.needs_embeddings is False

    def test_mismatched_provider(self, role_file, monkeypatch):
        """User has groq but role wants openai."""
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
        with patch("initrunner.services.providers._is_ollama_running", return_value=False):
            compat = check_role_provider_compatibility(role_file(ROLE_OPENAI))
        assert compat.role_provider == "openai"
        assert compat.user_has_key is False
        assert len(compat.available_providers) == 1
        assert compat.available_providers[0].provider == "groq"

    def test_rag_role_embedding_check_default(self, role_file, monkeypatch):
        """Anthropic role with RAG needs OPENAI_API_KEY for default embeddings."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        with patch("initrunner.services.providers._is_ollama_running", return_value=False):
            compat = check_role_provider_compatibility(role_file(ROLE_ANTHROPIC_WITH_RAG))
        assert compat.needs_embeddings is True
        assert compat.effective_embedding_provider == "openai"
        assert compat.has_embedding_key is False

    def test_rag_role_embedding_check_with_key(self, role_file, monkeypatch):
        """Anthropic role with RAG + OPENAI_API_KEY set for embeddings."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        with patch("initrunner.services.providers._is_ollama_running", return_value=False):
            compat = check_role_provider_compatibility(role_file(ROLE_ANTHROPIC_WITH_RAG))
        assert compat.needs_embeddings is True
        assert compat.has_embedding_key is True

    def test_explicit_embedding_provider(self, role_file, monkeypatch):
        """Role with explicit google embeddings checks GOOGLE_API_KEY."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
        monkeypatch.setenv("GOOGLE_API_KEY", "gcp-test")
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        with patch("initrunner.services.providers._is_ollama_running", return_value=False):
            compat = check_role_provider_compatibility(role_file(ROLE_WITH_EXPLICIT_EMBEDDINGS))
        assert compat.needs_embeddings is True
        assert compat.effective_embedding_provider == "google"
        assert compat.has_embedding_key is True

    def test_explicit_embedding_provider_missing_key(self, role_file, monkeypatch):
        """Role with explicit google embeddings but no GOOGLE_API_KEY."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        with patch("initrunner.services.providers._is_ollama_running", return_value=False):
            compat = check_role_provider_compatibility(role_file(ROLE_WITH_EXPLICIT_EMBEDDINGS))
        assert compat.effective_embedding_provider == "google"
        assert compat.has_embedding_key is False

    def test_memory_role_needs_embeddings(self, role_file, monkeypatch):
        """Role with memory config is flagged as needing embeddings."""
        monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        with patch("initrunner.services.providers._is_ollama_running", return_value=False):
            compat = check_role_provider_compatibility(role_file(ROLE_WITH_MEMORY))
        assert compat.needs_embeddings is True
        # groq defaults to openai embeddings
        assert compat.has_embedding_key is False

    def test_ollama_provider_check(self, role_file, monkeypatch):
        """Ollama role checks if Ollama is running, not env vars."""
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        with (
            patch("initrunner.services.providers._is_ollama_running", return_value=True),
            patch(
                "initrunner.services.providers._get_first_ollama_model",
                return_value="llama3.2",
            ),
        ):
            compat = check_role_provider_compatibility(role_file(ROLE_OLLAMA))
        assert compat.user_has_key is True
        assert compat.role_provider == "ollama"
