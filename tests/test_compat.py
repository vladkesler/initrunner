"""Tests for the _compat module."""

import pytest

from initrunner._compat import require_ingest, require_provider


class TestRequireProvider:
    def test_openai_always_available(self):
        require_provider("openai")  # should not raise

    def test_ollama_always_available(self):
        require_provider("ollama")  # should not raise — uses openai SDK

    def test_unknown_provider(self):
        with pytest.raises(RuntimeError, match="Unknown provider"):
            require_provider("nonexistent")

    def test_missing_provider_gives_install_hint(self):
        # groq is unlikely to be installed in test env
        with pytest.raises(RuntimeError, match="pip install initrunner"):
            require_provider("groq")


class TestRequireIngest:
    def test_missing_package_gives_hint(self):
        with pytest.raises(RuntimeError, match="pip install initrunner\\[ingest\\]"):
            require_ingest("pymupdf4llm")
