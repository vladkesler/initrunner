"""Tests for build_mcp_toolset with defer=true."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from initrunner.agent.schema.security import ToolSandboxConfig
from initrunner.agent.schema.tools import McpToolConfig
from initrunner.mcp._cache import CachedTool, cache_key, write_cache
from initrunner.mcp._deferred import DeferredMcpToolset
from initrunner.mcp.server import build_mcp_toolset

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ctx(role_dir: Path | None = None):
    ctx = MagicMock()
    ctx.role_dir = role_dir
    ctx.role.spec.security.tools = ToolSandboxConfig()
    return ctx


# ---------------------------------------------------------------------------
# Deferred path
# ---------------------------------------------------------------------------


class TestBuildDeferred:
    def test_returns_deferred_toolset_no_cache(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        monkeypatch.setattr("initrunner.mcp._cache.get_mcp_cache_dir", lambda: tmp_path)
        config = McpToolConfig(transport="stdio", command="echo", args=["hi"], defer=True)
        ctx = _make_ctx()

        # Patch build_transport so we don't actually spawn a process.
        with patch("initrunner.mcp.server.build_transport"):
            toolset = build_mcp_toolset(config, ctx)

        # The outermost toolset should be or wrap a DeferredMcpToolset.
        # (No filter/prefix, so it's the DeferredMcpToolset itself.)
        assert isinstance(toolset, DeferredMcpToolset)
        assert toolset._cached_defs is None  # no cache yet

    def test_returns_deferred_with_cache(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        monkeypatch.setattr("initrunner.mcp._cache.get_mcp_cache_dir", lambda: tmp_path)
        config = McpToolConfig(transport="stdio", command="echo", args=["hi"], defer=True)
        ctx = _make_ctx()

        # Prime the cache.
        key = cache_key(config, ctx.role_dir)
        write_cache(
            key,
            [
                CachedTool("tool_a", "A tool", {"type": "object"}, None),
            ],
        )

        with patch("initrunner.mcp.server.build_transport"):
            toolset = build_mcp_toolset(config, ctx)

        assert isinstance(toolset, DeferredMcpToolset)
        assert toolset._cached_defs is not None
        assert len(toolset._cached_defs) == 1
        assert toolset._cached_defs[0].name == "tool_a"

    def test_eager_when_defer_false(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        monkeypatch.setattr("initrunner.mcp._cache.get_mcp_cache_dir", lambda: tmp_path)
        config = McpToolConfig(transport="stdio", command="echo", args=["hi"], defer=False)
        ctx = _make_ctx()

        with (
            patch("initrunner.mcp.server.build_transport"),
            patch("initrunner.mcp.server.FastMCPToolset") as mock_ts,
        ):
            mock_ts.return_value = MagicMock()
            toolset = build_mcp_toolset(config, ctx)

        assert not isinstance(toolset, DeferredMcpToolset)


# ---------------------------------------------------------------------------
# Filter / prefix applied to deferred
# ---------------------------------------------------------------------------


class TestDeferredWithFilters:
    def test_filter_wraps_deferred(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        monkeypatch.setattr("initrunner.mcp._cache.get_mcp_cache_dir", lambda: tmp_path)
        config = McpToolConfig(
            transport="stdio",
            command="echo",
            args=["hi"],
            defer=True,
            tool_filter=["allowed_tool"],
        )
        ctx = _make_ctx()

        with patch("initrunner.mcp.server.build_transport"):
            toolset = build_mcp_toolset(config, ctx)

        # Should be a FilteredToolset wrapping a DeferredMcpToolset.
        assert not isinstance(toolset, DeferredMcpToolset)
        assert hasattr(toolset, "wrapped")  # WrapperToolset
        assert isinstance(toolset.wrapped, DeferredMcpToolset)

    def test_prefix_wraps_deferred(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        monkeypatch.setattr("initrunner.mcp._cache.get_mcp_cache_dir", lambda: tmp_path)
        config = McpToolConfig(
            transport="stdio",
            command="echo",
            args=["hi"],
            defer=True,
            tool_prefix="myprefix",
        )
        ctx = _make_ctx()

        with patch("initrunner.mcp.server.build_transport"):
            toolset = build_mcp_toolset(config, ctx)

        assert not isinstance(toolset, DeferredMcpToolset)
        assert hasattr(toolset, "wrapped")
        assert isinstance(toolset.wrapped, DeferredMcpToolset)
