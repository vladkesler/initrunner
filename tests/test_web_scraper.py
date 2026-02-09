"""Tests for the web_scraper tool."""

from unittest.mock import patch

from initrunner.agent.schema import RoleDefinition, WebScraperToolConfig
from initrunner.agent.tools._registry import ToolBuildContext
from initrunner.agent.tools.web_scraper import build_web_scraper_toolset


def _get_tool_func(toolset, name: str):
    """Extract a tool function from a FunctionToolset by name."""
    tool = toolset.tools.get(name)
    if tool is None:
        raise KeyError(f"Tool '{name}' not found in toolset")
    return tool.function


def _make_ctx(role_dir=None, ingest_store_path=None):
    """Build a ToolBuildContext for web scraper tests."""
    spec: dict = {
        "role": "test",
        "model": {"provider": "openai", "name": "gpt-4o-mini"},
        "security": {"tools": {"restrict_db_paths": False}},
    }
    if ingest_store_path is not None:
        spec["ingest"] = {
            "sources": ["./docs/**/*.md"],
            "store_path": str(ingest_store_path),
            "chunking": {"strategy": "fixed", "chunk_size": 100, "chunk_overlap": 0},
        }
    role = RoleDefinition.model_validate(
        {
            "apiVersion": "initrunner/v1",
            "kind": "Agent",
            "metadata": {"name": "test-agent", "description": "test"},
            "spec": spec,
        }
    )
    return ToolBuildContext(role=role, role_dir=role_dir)


class TestWebScraperToolset:
    def test_has_scrape_page_tool(self):
        config = WebScraperToolConfig()
        toolset = build_web_scraper_toolset(config, _make_ctx())
        assert "scrape_page" in toolset.tools

    def test_allowed_domain_rejects(self):
        config = WebScraperToolConfig(allowed_domains=["good.com"])
        ts = build_web_scraper_toolset(config, _make_ctx())
        func = _get_tool_func(ts, "scrape_page")

        result = func(url="https://notallowed.com/page")
        assert "not in the allowed domains" in result

    def test_blocked_domain_rejects(self):
        config = WebScraperToolConfig(blocked_domains=["blocked.com"])
        ts = build_web_scraper_toolset(config, _make_ctx())
        func = _get_tool_func(ts, "scrape_page")

        result = func(url="https://blocked.com/page")
        assert "blocked" in result

    def test_allowed_domain_accepts(self):
        config = WebScraperToolConfig(allowed_domains=["good.com"])
        ts = build_web_scraper_toolset(config, _make_ctx())
        func = _get_tool_func(ts, "scrape_page")

        with (
            patch(
                "initrunner.agent.tools.web_scraper.fetch_url_as_markdown",
                return_value="Good content",
            ),
            patch(
                "initrunner.agent.tools.web_scraper._embed_single",
                return_value=[1.0, 0.0, 0.0, 0.0],
            ),
        ):
            result = func(url="https://good.com/page")

        assert "Stored" in result
        assert "chunk" in result

    def test_scrape_stores_chunks(self, tmp_path):
        """Full integration: fetch → chunk → embed → store."""
        config = WebScraperToolConfig()
        store_path = str(tmp_path / "store.db")
        ctx = _make_ctx(ingest_store_path=store_path)

        with (
            patch(
                "initrunner.agent.tools.web_scraper.fetch_url_as_markdown",
                return_value="Test content for web scraper tool that is long enough",
            ),
            patch(
                "initrunner.agent.tools.web_scraper._embed_single",
                return_value=[1.0, 0.0, 0.0, 0.0],
            ),
        ):
            ts = build_web_scraper_toolset(config, ctx)
            func = _get_tool_func(ts, "scrape_page")
            result = func(url="https://example.com/page")

        assert "Stored" in result
        assert "chunk" in result
        assert "example.com" in result

    def test_fetch_error_returns_message(self):
        config = WebScraperToolConfig()
        ts = build_web_scraper_toolset(config, _make_ctx())
        func = _get_tool_func(ts, "scrape_page")

        with patch(
            "initrunner.agent.tools.web_scraper.fetch_url_as_markdown",
            side_effect=ConnectionError("timeout"),
        ):
            result = func(url="https://down.example.com/page")

        assert "Error fetching URL" in result

    def test_empty_content_returns_message(self):
        config = WebScraperToolConfig()
        ts = build_web_scraper_toolset(config, _make_ctx())
        func = _get_tool_func(ts, "scrape_page")

        with patch(
            "initrunner.agent.tools.web_scraper.fetch_url_as_markdown",
            return_value="   ",
        ):
            result = func(url="https://example.com/empty")

        assert "No content" in result

    def test_schema_summary(self):
        config = WebScraperToolConfig(allowed_domains=["a.com", "b.com"])
        assert "a.com" in config.summary()
        assert "b.com" in config.summary()

    def test_schema_summary_default(self):
        config = WebScraperToolConfig()
        assert config.summary() == "web_scraper"
