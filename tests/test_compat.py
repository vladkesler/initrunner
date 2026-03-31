"""Tests for the _compat module."""

from unittest.mock import patch

import pytest

from initrunner._compat import (
    MissingExtraError,
    is_extra_available,
    require_extra,
    require_ingest,
    require_provider,
)


class TestRequireProvider:
    def test_openai_always_available(self):
        require_provider("openai")  # should not raise

    def test_ollama_always_available(self):
        require_provider("ollama")  # should not raise -- uses openai SDK

    def test_unknown_provider(self):
        with pytest.raises(RuntimeError, match="Unknown provider"):
            require_provider("nonexistent")

    def test_xai_always_available(self):
        require_provider("xai")  # should not raise -- uses openai SDK

    def test_bedrock_known_provider(self):
        """bedrock should get an import hint, not 'Unknown provider'."""
        with pytest.raises(RuntimeError, match="uv pip install initrunner"):
            require_provider("bedrock")

    def test_missing_provider_gives_install_hint(self):
        # groq is unlikely to be installed in test env
        with pytest.raises(RuntimeError, match="uv pip install initrunner"):
            require_provider("groq")


class TestRequireIngest:
    def test_missing_package_gives_hint(self):
        with patch("initrunner._compat.importlib.import_module", side_effect=ImportError):
            with pytest.raises(MissingExtraError, match="uv pip install initrunner\\[ingest\\]"):
                require_ingest("pymupdf4llm")

    def test_is_subclass_of_runtime_error(self):
        """Callers catching RuntimeError should still work."""
        with patch("initrunner._compat.importlib.import_module", side_effect=ImportError):
            with pytest.raises(RuntimeError):
                require_ingest("pymupdf4llm")


class TestRequireExtra:
    def test_known_module_gives_extra_hint(self):
        with patch("initrunner._compat.importlib.import_module", side_effect=ImportError):
            with pytest.raises(MissingExtraError, match="uv pip install initrunner\\[search\\]"):
                require_extra("ddgs")

    def test_known_module_includes_pip_name(self):
        with patch("initrunner._compat.importlib.import_module", side_effect=ImportError):
            with pytest.raises(MissingExtraError, match="'ddgs'"):
                require_extra("ddgs")

    def test_explicit_extra_and_pip_name(self):
        with patch("initrunner._compat.importlib.import_module", side_effect=ImportError):
            with pytest.raises(MissingExtraError, match="uv pip install initrunner\\[myextra\\]"):
                require_extra("some_module", extra="myextra", pip_name="some-module")

    def test_unknown_module_generic_hint(self):
        with patch("initrunner._compat.importlib.import_module", side_effect=ImportError):
            with pytest.raises(MissingExtraError, match="uv pip install unknown_pkg"):
                require_extra("unknown_pkg")

    def test_available_module_does_not_raise(self):
        require_extra("os")  # stdlib, always available


class TestIsExtraAvailable:
    def test_available_module(self):
        assert is_extra_available("os") is True

    def test_missing_module(self):
        assert is_extra_available("nonexistent_pkg_xyz") is False
