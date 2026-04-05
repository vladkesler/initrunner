"""Tests for DeferredMcpToolset."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic_ai.tools import ToolDefinition

from initrunner.mcp._deferred import DeferredMcpToolset

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_tool_def(name: str = "read_file", desc: str = "Read a file") -> ToolDefinition:
    return ToolDefinition(
        name=name,
        description=desc,
        parameters_json_schema={"type": "object", "properties": {"path": {"type": "string"}}},
        metadata={"meta": None, "annotations": None, "output_schema": None},
    )


def _make_mcp_tool(name: str = "read_file", desc: str = "Read a file"):
    """Mimics a tool returned by ``client.list_tools()``."""
    tool = MagicMock()
    tool.name = name
    tool.description = desc
    tool.inputSchema = {"type": "object", "properties": {"path": {"type": "string"}}}
    tool.meta = None
    tool.annotations = None
    tool.outputSchema = None
    return tool


def _make_live_toolset(tools: list | None = None):
    """Build a mock FastMCPToolset."""
    ts = AsyncMock()
    ts.__aenter__ = AsyncMock(return_value=ts)
    ts.__aexit__ = AsyncMock(return_value=None)
    ts.client.list_tools = AsyncMock(return_value=tools or [_make_mcp_tool()])
    ts.get_tools = AsyncMock(return_value={"read_file": MagicMock()})
    ts.call_tool = AsyncMock(return_value="file contents")
    return ts


# ---------------------------------------------------------------------------
# Cache hit path
# ---------------------------------------------------------------------------


class TestCacheHit:
    def test_get_tools_serves_from_cache(self):
        defs = [_make_tool_def()]
        toolset = DeferredMcpToolset(
            cached_defs=defs,
            factory=lambda: _make_live_toolset(),
            cache_key="test-key",
        )

        tools = asyncio.run(toolset.get_tools(MagicMock()))
        assert "read_file" in tools
        assert tools["read_file"].tool_def.name == "read_file"
        assert tools["read_file"].tool_def.metadata == defs[0].metadata

    def test_no_connection_on_get_tools(self):
        factory = MagicMock()
        defs = [_make_tool_def()]
        toolset = DeferredMcpToolset(cached_defs=defs, factory=factory, cache_key="test-key")

        asyncio.run(toolset.get_tools(MagicMock()))
        factory.assert_not_called()  # no connection

    @patch("initrunner.mcp._deferred.write_cache")
    def test_call_tool_triggers_connect(self, mock_write):
        live = _make_live_toolset()
        defs = [_make_tool_def()]
        toolset = DeferredMcpToolset(
            cached_defs=defs,
            factory=lambda: live,
            cache_key="test-key",
        )

        ctx = MagicMock()
        tool = MagicMock()
        result = asyncio.run(toolset.call_tool("read_file", {"path": "/a"}, ctx, tool))

        live.__aenter__.assert_awaited_once()
        live.call_tool.assert_awaited_once_with("read_file", {"path": "/a"}, ctx, tool)
        assert result == "file contents"


# ---------------------------------------------------------------------------
# Cache miss path
# ---------------------------------------------------------------------------


class TestCacheMiss:
    @patch("initrunner.mcp._deferred.write_cache")
    def test_get_tools_connects_eagerly(self, mock_write):
        live = _make_live_toolset()
        toolset = DeferredMcpToolset(
            cached_defs=None,  # cache miss
            factory=lambda: live,
            cache_key="miss-key",
        )

        tools = asyncio.run(toolset.get_tools(MagicMock()))
        live.__aenter__.assert_awaited_once()
        live.get_tools.assert_awaited_once()
        assert tools is not None


# ---------------------------------------------------------------------------
# Schema drift
# ---------------------------------------------------------------------------


class TestSchemaDrift:
    @patch("initrunner.mcp._deferred.write_cache")
    def test_logs_drift_warning(
        self, mock_write, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
    ):
        import logging

        monkeypatch.setattr(logging.getLogger("initrunner"), "propagate", True)

        # Cached schema has "read_file"; live server has "write_file" instead.
        cached_def = _make_tool_def("read_file")
        live = _make_live_toolset([_make_mcp_tool("write_file", "Write a file")])

        toolset = DeferredMcpToolset(
            cached_defs=[cached_def],
            factory=lambda: live,
            cache_key="drift-key",
        )

        with caplog.at_level(logging.WARNING, logger="initrunner.mcp._deferred"):
            asyncio.run(toolset.call_tool("write_file", {}, MagicMock(), MagicMock()))

        assert any("schema drift" in r.message.lower() for r in caplog.records)
        assert any("read_file" in r.message for r in caplog.records)  # removed
        assert any("write_file" in r.message for r in caplog.records)  # added


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


class TestLifecycle:
    def test_aenter_is_noop(self):
        toolset = DeferredMcpToolset(
            cached_defs=[_make_tool_def()],
            factory=lambda: _make_live_toolset(),
            cache_key="lc-key",
        )

        result = asyncio.run(toolset.__aenter__())
        assert result is toolset

    @patch("initrunner.mcp._deferred.write_cache")
    def test_aexit_cleans_up_live(self, mock_write):
        live = _make_live_toolset()
        toolset = DeferredMcpToolset(
            cached_defs=[_make_tool_def()],
            factory=lambda: live,
            cache_key="lc-key",
        )

        # Connect, then exit.
        asyncio.run(toolset.call_tool("read_file", {}, MagicMock(), MagicMock()))
        asyncio.run(toolset.__aexit__(None, None, None))

        live.__aexit__.assert_awaited_once()

    def test_aexit_noop_when_not_connected(self):
        toolset = DeferredMcpToolset(
            cached_defs=[_make_tool_def()],
            factory=lambda: _make_live_toolset(),
            cache_key="lc-key",
        )
        # Should not raise.
        asyncio.run(toolset.__aexit__(None, None, None))


# ---------------------------------------------------------------------------
# Concurrency: double-connect guard
# ---------------------------------------------------------------------------


class TestConcurrency:
    @patch("initrunner.mcp._deferred.write_cache")
    def test_lock_prevents_double_connect(self, mock_write):
        connect_count = 0
        live = _make_live_toolset()

        original_aenter = live.__aenter__

        async def counting_aenter():
            nonlocal connect_count
            connect_count += 1
            return await original_aenter()

        live.__aenter__ = AsyncMock(side_effect=counting_aenter)

        toolset = DeferredMcpToolset(
            cached_defs=[_make_tool_def()],
            factory=lambda: live,
            cache_key="conc-key",
        )

        async def race():
            await asyncio.gather(
                toolset.call_tool("read_file", {}, MagicMock(), MagicMock()),
                toolset.call_tool("read_file", {}, MagicMock(), MagicMock()),
            )

        asyncio.run(race())
        assert connect_count == 1
