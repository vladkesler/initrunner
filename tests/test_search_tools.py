"""Tests for the search tool: schema, toolset builder, and tool functions."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from initrunner.agent._env import resolve_env_vars
from initrunner.agent.schema.role import AgentSpec
from initrunner.agent.schema.tools import SearchToolConfig
from initrunner.agent.tools._registry import ToolBuildContext
from initrunner.agent.tools.search import (
    _format_results,
    _search_duckduckgo,
    build_search_toolset,
)


def _make_ctx():
    """Build a minimal ToolBuildContext for tests."""
    from initrunner.agent.schema.role import RoleDefinition

    role = RoleDefinition.model_validate(
        {
            "apiVersion": "initrunner/v1",
            "kind": "Agent",
            "metadata": {"name": "test-agent", "description": "test"},
            "spec": {
                "role": "test",
                "model": {"provider": "openai", "name": "gpt-5-mini"},
            },
        }
    )
    return ToolBuildContext(role=role)


def _mock_ddgs_module(mock_ddgs):
    """Create a mock ddgs module with the given DDGS instance."""
    mock_mod = MagicMock(DDGS=MagicMock(return_value=mock_ddgs))
    return {"ddgs": mock_mod}


def _make_ddgs_mock():
    """Create a mock DDGS instance."""
    return MagicMock()


# ---------------------------------------------------------------------------
# Schema / config validation tests
# ---------------------------------------------------------------------------


class TestSearchConfig:
    def test_default_provider(self):
        config = SearchToolConfig()
        assert config.provider == "duckduckgo"
        assert config.api_key == ""
        assert config.max_results == 10
        assert config.safe_search is True
        assert config.timeout_seconds == 15

    def test_paid_provider_requires_api_key(self):
        for provider in ("serpapi", "brave", "tavily"):
            with pytest.raises(ValueError, match="requires 'api_key'"):
                SearchToolConfig(provider=provider)

    def test_paid_provider_with_api_key(self):
        for provider in ("serpapi", "brave", "tavily"):
            config = SearchToolConfig(provider=provider, api_key="sk-test-123")
            assert config.provider == provider
            assert config.api_key == "sk-test-123"

    def test_summary(self):
        config = SearchToolConfig()
        assert config.summary() == "search: duckduckgo"

    def test_summary_paid(self):
        config = SearchToolConfig(provider="tavily", api_key="key")
        assert config.summary() == "search: tavily"

    def test_in_agent_spec(self):
        spec_data = {
            "role": "Test agent",
            "model": {"provider": "openai", "name": "gpt-5-mini"},
            "tools": [{"type": "search"}],
        }
        spec = AgentSpec.model_validate(spec_data)
        assert len(spec.tools) == 1
        assert isinstance(spec.tools[0], SearchToolConfig)

    def test_in_agent_spec_with_provider(self):
        spec_data = {
            "role": "Test agent",
            "model": {"provider": "openai", "name": "gpt-5-mini"},
            "tools": [
                {
                    "type": "search",
                    "provider": "brave",
                    "api_key": "${BRAVE_KEY}",
                }
            ],
        }
        spec = AgentSpec.model_validate(spec_data)
        assert isinstance(spec.tools[0], SearchToolConfig)
        assert spec.tools[0].provider == "brave"


# ---------------------------------------------------------------------------
# Toolset builder tests
# ---------------------------------------------------------------------------


class TestSearchToolset:
    def test_builds_toolset(self):
        config = SearchToolConfig()
        toolset = build_search_toolset(config, _make_ctx())
        assert "web_search" in toolset.tools
        assert "news_search" in toolset.tools

    def test_env_var_resolution(self):
        os.environ["TEST_SEARCH_KEY"] = "resolved_key"
        try:
            config = SearchToolConfig(provider="serpapi", api_key="${TEST_SEARCH_KEY}")
            assert resolve_env_vars(config.api_key) == "resolved_key"
        finally:
            os.environ.pop("TEST_SEARCH_KEY")


# ---------------------------------------------------------------------------
# Format helper tests
# ---------------------------------------------------------------------------


class TestFormatResults:
    def test_empty_results(self):
        assert _format_results([]) == "No results found."

    def test_single_result(self):
        results = [
            {
                "title": "Example",
                "url": "https://example.com",
                "snippet": "A test",
            }
        ]
        output = _format_results(results)
        assert "1. **Example**" in output
        assert "https://example.com" in output
        assert "A test" in output

    def test_multiple_results(self):
        results = [
            {
                "title": f"Result {i}",
                "url": f"https://example.com/{i}",
                "snippet": f"Snippet {i}",
            }
            for i in range(3)
        ]
        output = _format_results(results)
        assert "1. **Result 0**" in output
        assert "2. **Result 1**" in output
        assert "3. **Result 2**" in output


# ---------------------------------------------------------------------------
# DuckDuckGo provider tests (mocked via _PROVIDERS patch)
# ---------------------------------------------------------------------------


class TestDuckDuckGoToolIntegration:
    def test_web_search(self):
        mock_provider = MagicMock(
            return_value=[
                {
                    "title": "Test Result",
                    "url": "https://example.com",
                    "snippet": "A snippet",
                },
            ]
        )

        with patch(
            "initrunner.agent.tools.search._PROVIDERS",
            {"duckduckgo": mock_provider},
        ):
            config = SearchToolConfig()
            toolset = build_search_toolset(config, _make_ctx())
            fn = toolset.tools["web_search"].function

            result = fn(query="test query")
            assert "Test Result" in result
            assert "https://example.com" in result
            mock_provider.assert_called_once()
            assert mock_provider.call_args.kwargs["news"] is False

    def test_news_search(self):
        mock_provider = MagicMock(
            return_value=[
                {
                    "title": "News Item",
                    "url": "https://news.example.com",
                    "snippet": "Breaking news",
                },
            ]
        )

        with patch(
            "initrunner.agent.tools.search._PROVIDERS",
            {"duckduckgo": mock_provider},
        ):
            config = SearchToolConfig()
            toolset = build_search_toolset(config, _make_ctx())
            fn = toolset.tools["news_search"].function

            result = fn(query="test news")
            assert "News Item" in result
            assert "https://news.example.com" in result
            assert mock_provider.call_args.kwargs["news"] is True


# ---------------------------------------------------------------------------
# DuckDuckGo provider direct tests (mocked DDGS)
# ---------------------------------------------------------------------------


class TestDuckDuckGoProviderDirect:
    """Test the _search_duckduckgo function directly with mocked DDGS."""

    def test_web_search_maps_fields(self):
        mock_ddgs = _make_ddgs_mock()
        mock_ddgs.text.return_value = [
            {
                "title": "DDG Result",
                "href": "https://ddg.example.com",
                "body": "DDG body",
            },
        ]

        with patch.dict("sys.modules", _mock_ddgs_module(mock_ddgs)):
            results = _search_duckduckgo(
                query="test",
                max_results=5,
                safe_search=True,
                api_key="",
                timeout=15,
            )
            assert len(results) == 1
            assert results[0]["title"] == "DDG Result"
            assert results[0]["url"] == "https://ddg.example.com"
            assert results[0]["snippet"] == "DDG body"

    def test_news_search_timelimit_day(self):
        mock_ddgs = _make_ddgs_mock()
        mock_ddgs.news.return_value = [
            {
                "title": "News",
                "url": "https://news.example.com",
                "body": "News body",
            },
        ]

        with patch.dict("sys.modules", _mock_ddgs_module(mock_ddgs)):
            results = _search_duckduckgo(
                query="test",
                max_results=5,
                safe_search=True,
                api_key="",
                timeout=15,
                news=True,
                days_back=1,
            )
            mock_ddgs.news.assert_called_once_with(
                "test",
                max_results=5,
                timelimit="d",
                safesearch="moderate",
            )
            assert len(results) == 1

    def test_news_search_timelimit_week(self):
        mock_ddgs = _make_ddgs_mock()
        mock_ddgs.news.return_value = []

        with patch.dict("sys.modules", _mock_ddgs_module(mock_ddgs)):
            _search_duckduckgo(
                query="test",
                max_results=5,
                safe_search=True,
                api_key="",
                timeout=15,
                news=True,
                days_back=5,
            )
            mock_ddgs.news.assert_called_once_with(
                "test",
                max_results=5,
                timelimit="w",
                safesearch="moderate",
            )

    def test_news_search_timelimit_month(self):
        mock_ddgs = _make_ddgs_mock()
        mock_ddgs.news.return_value = []

        with patch.dict("sys.modules", _mock_ddgs_module(mock_ddgs)):
            _search_duckduckgo(
                query="test",
                max_results=5,
                safe_search=True,
                api_key="",
                timeout=15,
                news=True,
                days_back=30,
            )
            mock_ddgs.news.assert_called_once_with(
                "test",
                max_results=5,
                timelimit="m",
                safesearch="moderate",
            )

    def test_safe_search_off(self):
        mock_ddgs = _make_ddgs_mock()
        mock_ddgs.text.return_value = []

        with patch.dict("sys.modules", _mock_ddgs_module(mock_ddgs)):
            _search_duckduckgo(
                query="test",
                max_results=5,
                safe_search=False,
                api_key="",
                timeout=15,
            )
            mock_ddgs.text.assert_called_once_with("test", max_results=5, safesearch="off")


# ---------------------------------------------------------------------------
# SerpAPI provider tests (mocked)
# ---------------------------------------------------------------------------


class TestSerpAPIProvider:
    def test_web_search(self):
        from initrunner.agent.tools.search import _search_serpapi

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "organic_results": [
                {
                    "title": "Serp Result",
                    "link": "https://serp.example.com",
                    "snippet": "Serp snippet",
                },
            ]
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_response

        import httpx

        with patch.object(httpx, "Client", return_value=mock_client):
            results = _search_serpapi(
                query="test",
                max_results=5,
                safe_search=True,
                api_key="test-key",
                timeout=15,
            )
            assert len(results) == 1
            assert results[0]["title"] == "Serp Result"
            assert results[0]["url"] == "https://serp.example.com"


# ---------------------------------------------------------------------------
# Tool function error handling tests
# ---------------------------------------------------------------------------


class TestSearchErrorHandling:
    def test_missing_ddgs_package(self):
        """When ddgs is not installed, error message is returned."""
        config = SearchToolConfig()
        err_msg = "ddgs is required: pip install ddgs or pip install initrunner[search]"

        with patch(
            "initrunner.agent.tools.search._PROVIDERS",
            {"duckduckgo": MagicMock(side_effect=ImportError(err_msg))},
        ):
            toolset = build_search_toolset(config, _make_ctx())
            fn = toolset.tools["web_search"].function
            result = fn(query="test")
            assert "ddgs is required" in result

    def test_search_api_error(self):
        """API errors are returned as error messages."""
        config = SearchToolConfig()

        with patch(
            "initrunner.agent.tools.search._PROVIDERS",
            {"duckduckgo": MagicMock(side_effect=RuntimeError("API rate limited"))},
        ):
            toolset = build_search_toolset(config, _make_ctx())
            fn = toolset.tools["web_search"].function
            result = fn(query="test")
            assert "Error: search failed:" in result
            assert "API rate limited" in result

    def test_search_timeout(self):
        """Timeout errors are returned as error messages."""
        config = SearchToolConfig(timeout_seconds=5)

        with patch(
            "initrunner.agent.tools.search._PROVIDERS",
            {"duckduckgo": MagicMock(side_effect=TimeoutError("timed out"))},
        ):
            toolset = build_search_toolset(config, _make_ctx())
            fn = toolset.tools["web_search"].function
            result = fn(query="test")
            assert "Error: search timed out after 5s" in result

    def test_news_search_api_error(self):
        """News search API errors are returned as error messages."""
        config = SearchToolConfig()

        with patch(
            "initrunner.agent.tools.search._PROVIDERS",
            {"duckduckgo": MagicMock(side_effect=RuntimeError("Network error"))},
        ):
            toolset = build_search_toolset(config, _make_ctx())
            fn = toolset.tools["news_search"].function
            result = fn(query="test")
            assert "Error: search failed:" in result

    def test_result_truncation(self):
        """Large results are truncated."""
        config = SearchToolConfig()

        large_results = [
            {
                "title": f"Result {i}",
                "url": f"https://example.com/{i}",
                "snippet": "X" * 10_000,
            }
            for i in range(20)
        ]

        with patch(
            "initrunner.agent.tools.search._PROVIDERS",
            {"duckduckgo": MagicMock(return_value=large_results)},
        ):
            toolset = build_search_toolset(config, _make_ctx())
            fn = toolset.tools["web_search"].function
            result = fn(query="test", num_results=20)
            assert len(result) <= 65_536 + len("\n[truncated]")

    def test_num_results_capped_by_max_results(self):
        """num_results is capped by config.max_results."""
        config = SearchToolConfig(max_results=3)
        mock_provider = MagicMock(return_value=[])

        with patch(
            "initrunner.agent.tools.search._PROVIDERS",
            {"duckduckgo": mock_provider},
        ):
            toolset = build_search_toolset(config, _make_ctx())
            fn = toolset.tools["web_search"].function
            fn(query="test", num_results=100)
            # Should be capped to max_results=3
            call_kwargs = mock_provider.call_args
            assert call_kwargs.kwargs["max_results"] == 3
