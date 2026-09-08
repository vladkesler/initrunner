"""Tests for the web_scraper tool."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from initrunner.agent.schema.role import RoleDefinition
from initrunner.agent.schema.tools import WebScraperToolConfig
from initrunner.agent.tools._registry import ToolBuildContext
from initrunner.agent.tools.web_scraper import build_web_scraper_toolset
from initrunner.ingestion.chunker import Chunk


async def _fake_embed(_embedder, texts, **_kwargs):
    """Return deterministic 4-dim vectors, one per text."""
    return [[1.0, 0.0, 0.0, 0.0]] * len(texts)


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
        "model": {"provider": "openai", "name": "gpt-5-mini"},
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

        result = asyncio.run(func(url="https://notallowed.com/page"))
        assert "not in the allowed domains" in result

    def test_blocked_domain_rejects(self):
        config = WebScraperToolConfig(blocked_domains=["blocked.com"])
        ts = build_web_scraper_toolset(config, _make_ctx())
        func = _get_tool_func(ts, "scrape_page")

        result = asyncio.run(func(url="https://blocked.com/page"))
        assert "blocked" in result

    def test_allowed_domain_accepts(self):
        config = WebScraperToolConfig(allowed_domains=["good.com"])
        ts = build_web_scraper_toolset(config, _make_ctx())
        func = _get_tool_func(ts, "scrape_page")

        with (
            patch(
                "initrunner._html.fetch_url_as_markdown_async",
                AsyncMock(return_value="Good content"),
            ),
            patch("initrunner.ingestion.embeddings.create_embedder", return_value=MagicMock()),
            patch("initrunner.ingestion.embeddings.embed_texts", new=_fake_embed),
        ):
            result = asyncio.run(func(url="https://good.com/page"))

        assert "Stored" in result
        assert "chunk" in result

    def test_scrape_stores_chunks(self, tmp_path):
        """Full integration: fetch → chunk → embed → store."""
        config = WebScraperToolConfig()
        store_path = str(tmp_path / "store.db")
        ctx = _make_ctx(ingest_store_path=store_path)

        with (
            patch(
                "initrunner._html.fetch_url_as_markdown_async",
                AsyncMock(return_value="Test content for web scraper tool that is long enough"),
            ),
            patch("initrunner.ingestion.embeddings.create_embedder", return_value=MagicMock()),
            patch("initrunner.ingestion.embeddings.embed_texts", new=_fake_embed),
        ):
            ts = build_web_scraper_toolset(config, ctx)
            func = _get_tool_func(ts, "scrape_page")
            result = asyncio.run(func(url="https://example.com/page"))

        assert "Stored" in result
        assert "chunk" in result
        assert "example.com" in result

    def test_scrape_embeds_in_sequential_batches(self):
        """Regression for #248: one embedder, batched requests, never one call per chunk."""
        url = "https://example.com/big-page"
        chunks = [Chunk(text=f"chunk-{i}", source=url, index=i) for i in range(1200)]
        batch_sizes: list[int] = []
        active = 0
        max_active = 0
        stored: dict = {}

        async def tracking_embed(_embedder, texts, **_kwargs):
            nonlocal active, max_active
            active += 1
            max_active = max(max_active, active)
            batch_sizes.append(len(texts))
            await asyncio.sleep(0)
            active -= 1
            return [[float(t.split("-")[1]), 0.0, 0.0, 0.0] for t in texts]

        def capture_store(_store_config, _url, chunk_texts, embeddings):
            stored["embeddings"] = embeddings
            return f"Stored {len(chunk_texts)} chunks from {url}"

        create_embedder = MagicMock(return_value=MagicMock())
        with (
            patch("initrunner._html.fetch_url_as_markdown_async", AsyncMock(return_value="page")),
            patch("initrunner.agent.tools.web_scraper.chunk_text", return_value=chunks),
            patch("initrunner.ingestion.embeddings.create_embedder", create_embedder),
            patch("initrunner.ingestion.embeddings.embed_texts", new=tracking_embed),
            patch("initrunner.agent.tools.web_scraper._store_chunks", capture_store),
        ):
            ts = build_web_scraper_toolset(WebScraperToolConfig(), _make_ctx())
            func = _get_tool_func(ts, "scrape_page")
            result = asyncio.run(func(url=url))

        assert "Stored 1200 chunks" in result
        assert create_embedder.call_count == 1
        assert batch_sizes == [500, 500, 200]
        assert max_active == 1
        assert [v[0] for v in stored["embeddings"]] == [float(i) for i in range(1200)]

    def test_fetch_error_returns_message(self):
        config = WebScraperToolConfig()
        ts = build_web_scraper_toolset(config, _make_ctx())
        func = _get_tool_func(ts, "scrape_page")

        with patch(
            "initrunner._html.fetch_url_as_markdown_async",
            AsyncMock(side_effect=ConnectionError("timeout")),
        ):
            result = asyncio.run(func(url="https://down.example.com/page"))

        assert "Error fetching URL" in result

    def test_empty_content_returns_message(self):
        config = WebScraperToolConfig()
        ts = build_web_scraper_toolset(config, _make_ctx())
        func = _get_tool_func(ts, "scrape_page")

        with patch(
            "initrunner._html.fetch_url_as_markdown_async",
            AsyncMock(return_value="   "),
        ):
            result = asyncio.run(func(url="https://example.com/empty"))

        assert "No content" in result

    def test_schema_summary(self):
        config = WebScraperToolConfig(allowed_domains=["a.com", "b.com"])
        assert "a.com" in config.summary()
        assert "b.com" in config.summary()

    def test_schema_summary_default(self):
        config = WebScraperToolConfig()
        assert config.summary() == "web_scraper"
