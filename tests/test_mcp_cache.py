"""Tests for MCP tool schema cache."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic_ai.tools import ToolDefinition

from initrunner.agent.schema.tools import McpToolConfig
from initrunner.mcp._cache import (
    CACHE_VERSION,
    CachedTool,
    cache_age_seconds,
    cache_key,
    diff_schemas,
    invalidate_cache,
    read_cache,
    to_tool_definitions,
    write_cache,
)

# ---------------------------------------------------------------------------
# cache_key
# ---------------------------------------------------------------------------


class TestCacheKey:
    """Cache key uses resolved transport identity, not the Hub's display hash."""

    def test_identical_configs_same_key(self):
        a = McpToolConfig(transport="stdio", command="npx", args=["server-a", "--flag"])
        b = McpToolConfig(transport="stdio", command="npx", args=["server-a", "--flag"])
        assert cache_key(a, None) == cache_key(b, None)

    def test_arg_order_matters(self):
        """Hub hash sorts args; cache key must not."""
        a = McpToolConfig(transport="stdio", command="npx", args=["--foo", "--bar"])
        b = McpToolConfig(transport="stdio", command="npx", args=["--bar", "--foo"])
        assert cache_key(a, None) != cache_key(b, None)

    def test_env_values_matter(self, monkeypatch: pytest.MonkeyPatch):
        """Hub hash ignores env values; cache key must include them."""
        monkeypatch.setenv("MY_VAR", "alpha")
        a = McpToolConfig(
            transport="stdio",
            command="npx",
            args=["server"],
            env={"MY_VAR": "${MY_VAR}"},
        )
        key_alpha = cache_key(a, None)

        monkeypatch.setenv("MY_VAR", "beta")
        key_beta = cache_key(a, None)

        assert key_alpha != key_beta

    def test_cwd_resolved_against_role_dir(self, tmp_path: Path):
        """Relative cwd must be resolved like _transport.py does."""
        cfg = McpToolConfig(transport="stdio", command="npx", args=["s"], cwd="sub")
        key_a = cache_key(cfg, tmp_path / "roles" / "agentA")
        key_b = cache_key(cfg, tmp_path / "roles" / "agentB")
        assert key_a != key_b

    def test_cwd_absolute_ignores_role_dir(self, tmp_path: Path):
        cfg = McpToolConfig(transport="stdio", command="npx", args=["s"], cwd=str(tmp_path))
        assert cache_key(cfg, Path("/a")) == cache_key(cfg, Path("/b"))

    def test_sse_url_and_headers(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("TOKEN", "abc")
        cfg = McpToolConfig(
            transport="sse",
            url="https://mcp.example.com/sse",
            headers={"Authorization": "Bearer ${TOKEN}"},
        )
        key_a = cache_key(cfg, None)

        monkeypatch.setenv("TOKEN", "xyz")
        key_b = cache_key(cfg, None)
        assert key_a != key_b

    def test_different_transport_different_key(self):
        a = McpToolConfig(transport="stdio", command="npx", args=["s"])
        b = McpToolConfig(transport="sse", url="http://localhost:8080/sse")
        assert cache_key(a, None) != cache_key(b, None)


# ---------------------------------------------------------------------------
# read / write / invalidate
# ---------------------------------------------------------------------------


class TestReadWrite:
    def test_round_trip(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        monkeypatch.setattr("initrunner.mcp._cache.get_mcp_cache_dir", lambda: tmp_path)

        tools = [
            CachedTool(
                name="read_file",
                description="Read a file",
                parameters_json_schema={
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                },
                metadata={
                    "meta": None,
                    "annotations": {"readOnlyHint": True},
                    "output_schema": None,
                },
            ),
        ]
        write_cache("test-key", tools)

        entry = read_cache("test-key")
        assert entry is not None
        assert entry.version == CACHE_VERSION
        assert len(entry.tools) == 1
        assert entry.tools[0].name == "read_file"
        assert entry.tools[0].metadata == {
            "meta": None,
            "annotations": {"readOnlyHint": True},
            "output_schema": None,
        }

    def test_read_missing_returns_none(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        monkeypatch.setattr("initrunner.mcp._cache.get_mcp_cache_dir", lambda: tmp_path)
        assert read_cache("nonexistent") is None

    def test_corrupt_file_returns_none(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        monkeypatch.setattr("initrunner.mcp._cache.get_mcp_cache_dir", lambda: tmp_path)
        (tmp_path / "corrupt.json").write_text("not json{{{")
        assert read_cache("corrupt") is None

    def test_wrong_version_returns_none(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        monkeypatch.setattr("initrunner.mcp._cache.get_mcp_cache_dir", lambda: tmp_path)
        data = {"version": 999, "cached_at": "2026-01-01T00:00:00Z", "tools": []}
        (tmp_path / "old.json").write_text(json.dumps(data))
        assert read_cache("old") is None

    def test_invalidate_removes_file(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        monkeypatch.setattr("initrunner.mcp._cache.get_mcp_cache_dir", lambda: tmp_path)
        write_cache("to-delete", [])
        assert invalidate_cache("to-delete") is True
        assert read_cache("to-delete") is None

    def test_invalidate_missing_returns_false(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        monkeypatch.setattr("initrunner.mcp._cache.get_mcp_cache_dir", lambda: tmp_path)
        assert invalidate_cache("nope") is False


# ---------------------------------------------------------------------------
# cache_age_seconds
# ---------------------------------------------------------------------------


class TestCacheAge:
    def test_returns_positive_for_recent_cache(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        monkeypatch.setattr("initrunner.mcp._cache.get_mcp_cache_dir", lambda: tmp_path)
        write_cache("age-test", [])
        age = cache_age_seconds("age-test")
        assert age is not None
        assert 0 <= age < 5  # written just now

    def test_returns_none_for_missing(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        monkeypatch.setattr("initrunner.mcp._cache.get_mcp_cache_dir", lambda: tmp_path)
        assert cache_age_seconds("nope") is None


# ---------------------------------------------------------------------------
# diff_schemas
# ---------------------------------------------------------------------------


class TestDiffSchemas:
    def test_no_diff_identical(self):
        tools = [CachedTool("a", "desc", {"type": "object"}, None)]
        assert diff_schemas(tools, tools) == []

    def test_tool_added(self):
        old = [CachedTool("a", "desc", {}, None)]
        new = [CachedTool("a", "desc", {}, None), CachedTool("b", "new", {}, None)]
        diffs = diff_schemas(old, new)
        assert any("added" in d and "b" in d for d in diffs)

    def test_tool_removed(self):
        old = [CachedTool("a", "desc", {}, None), CachedTool("b", "old", {}, None)]
        new = [CachedTool("a", "desc", {}, None)]
        diffs = diff_schemas(old, new)
        assert any("removed" in d and "b" in d for d in diffs)

    def test_parameters_changed(self):
        old = [CachedTool("a", "desc", {"type": "object"}, None)]
        new = [CachedTool("a", "desc", {"type": "string"}, None)]
        diffs = diff_schemas(old, new)
        assert any("parameters" in d for d in diffs)

    def test_metadata_changed(self):
        old = [CachedTool("a", "desc", {}, {"meta": None})]
        new = [CachedTool("a", "desc", {}, {"meta": {"key": "val"}})]
        diffs = diff_schemas(old, new)
        assert any("metadata" in d for d in diffs)


# ---------------------------------------------------------------------------
# to_tool_definitions
# ---------------------------------------------------------------------------


class TestToToolDefinitions:
    def test_converts_with_metadata(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        monkeypatch.setattr("initrunner.mcp._cache.get_mcp_cache_dir", lambda: tmp_path)

        tools = [
            CachedTool(
                name="query",
                description="Run a query",
                parameters_json_schema={
                    "type": "object",
                    "properties": {"sql": {"type": "string"}},
                },
                metadata={"meta": {"x": 1}, "annotations": None, "output_schema": None},
            ),
        ]
        write_cache("conv-test", tools)
        entry = read_cache("conv-test")
        assert entry is not None

        defs = to_tool_definitions(entry)
        assert len(defs) == 1
        td = defs[0]
        assert isinstance(td, ToolDefinition)
        assert td.name == "query"
        assert td.description == "Run a query"
        assert td.parameters_json_schema == {
            "type": "object",
            "properties": {"sql": {"type": "string"}},
        }
        assert td.metadata == {"meta": {"x": 1}, "annotations": None, "output_schema": None}
