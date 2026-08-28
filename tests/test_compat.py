"""Tests for the _compat module."""

from unittest.mock import patch

import pytest

from initrunner._compat import (
    _PROVIDER_EXTRAS,
    _PROVIDER_PACKAGES,
    MissingExtraError,
    is_extra_available,
    is_extra_installed,
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

    def test_xai_needs_its_own_sdk(self):
        """xai:name builds XaiModel on xai-sdk, not an openai-compatible client."""
        assert _PROVIDER_PACKAGES["xai"] == "xai_sdk"
        with patch("initrunner._compat.importlib.import_module", side_effect=ImportError):
            with pytest.raises(MissingExtraError, match=r"uv pip install initrunner\[xai\]"):
                require_provider("xai")

    def test_google_marker_is_the_package_pydantic_ai_installs(self):
        """pydantic-ai-slim[google] ships google-genai, not google-generativeai."""
        assert _PROVIDER_PACKAGES["google"] == "google.genai"

    def test_every_provider_extra_is_a_real_extra(self):
        import tomllib
        from pathlib import Path

        pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
        declared = set(tomllib.loads(pyproject.read_text())["project"]["optional-dependencies"])
        assert set(_PROVIDER_EXTRAS.values()) <= declared

    def test_provider_gap_is_a_missing_extra_error(self):
        """The central handler and the install prompt both key off this type."""
        with patch("initrunner._compat.importlib.import_module", side_effect=ImportError):
            with pytest.raises(MissingExtraError) as exc:
                require_provider("anthropic")
        assert exc.value.extra == "anthropic"
        assert exc.value.pip_name == "anthropic"

    def test_bedrock_known_provider(self):
        """bedrock should get an import hint, not 'Unknown provider'."""
        with patch("initrunner._compat.importlib.import_module", side_effect=ImportError):
            with pytest.raises(RuntimeError, match="uv pip install initrunner"):
                require_provider("bedrock")

    def test_missing_provider_gives_install_hint(self):
        """Missing SDK should give an install hint with the correct extra."""
        with patch("initrunner._compat.importlib.import_module", side_effect=ImportError):
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


class TestMissingExtraErrorAttributes:
    def test_carries_extra_and_pip_name(self):
        with patch("initrunner._compat.importlib.import_module", side_effect=ImportError):
            with pytest.raises(MissingExtraError) as exc:
                require_extra("ddgs")
        assert exc.value.extra == "search"
        assert exc.value.pip_name == "ddgs"

    def test_message_is_unchanged(self):
        """Docs, dashboard 501s and tool results all quote this text."""
        with patch("initrunner._compat.importlib.import_module", side_effect=ImportError):
            with pytest.raises(MissingExtraError) as exc:
                require_extra("ddgs")
        assert str(exc.value) == "'ddgs' is required: uv pip install initrunner[search]"

    def test_attributes_default_to_none(self):
        """A few sites raise this with a hand-built message and no extra."""
        err = MissingExtraError("something is missing")
        assert err.extra is None and err.pip_name is None

    def test_unknown_module_has_no_extra(self):
        with patch("initrunner._compat.importlib.import_module", side_effect=ImportError):
            with pytest.raises(MissingExtraError) as exc:
                require_extra("unknown_pkg")
        assert exc.value.extra is None


class TestIsExtraInstalled:
    def test_marker_module_present(self):
        with patch("initrunner._compat.importlib.import_module", return_value=object()):
            assert is_extra_installed("search") is True

    def test_marker_module_absent(self):
        with patch("initrunner._compat.importlib.import_module", side_effect=ImportError):
            assert is_extra_installed("search") is False

    def test_observability_marker_matches_its_gate(self):
        """require_observability imports opentelemetry.sdk, so that is the marker."""
        from initrunner._compat import _EXTRA_MARKER_MODULES

        assert _EXTRA_MARKER_MODULES["observability"] == "opentelemetry.sdk"

    def test_unknown_extra_never_blocks(self):
        assert is_extra_installed("some-future-extra") is True
