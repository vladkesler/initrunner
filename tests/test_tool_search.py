"""Tests for the tool search meta-tool."""

from __future__ import annotations

import asyncio
import threading
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from initrunner.agent.schema.role import RoleDefinition, ToolSearchConfig
from initrunner.agent.tools.tool_search import (
    ToolSearchManager,
    _BM25Index,
    _tokenize,
    build_tool_search_toolset,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_tool_def(name: str, description: str = "", params: dict | None = None):
    """Create a mock ToolDefinition-like object for testing."""
    td = MagicMock()
    td.name = name
    td.description = description
    td.parameters_json_schema = params or {"type": "object", "properties": {}}
    return td


def _minimal_role_data(**spec_overrides) -> dict:
    spec = {
        "role": "You are a test agent.",
        "model": {"provider": "anthropic", "name": "claude-sonnet-4-5-20250929"},
        **spec_overrides,
    }
    return {
        "apiVersion": "initrunner/v1",
        "kind": "Agent",
        "metadata": {"name": "test-agent", "description": "A test agent"},
        "spec": spec,
    }


# ---------------------------------------------------------------------------
# _tokenize
# ---------------------------------------------------------------------------


class TestTokenize:
    def test_snake_case(self):
        tokens = _tokenize("send_slack_message")
        assert "send" in tokens
        assert "slack" in tokens
        assert "message" in tokens

    def test_camel_case(self):
        tokens = _tokenize("sendSlackMessage")
        assert "send" in tokens
        assert "slack" in tokens
        assert "message" in tokens

    def test_stopwords_removed(self):
        tokens = _tokenize("search for a file in the directory")
        assert "a" not in tokens
        assert "for" not in tokens
        assert "in" not in tokens
        assert "the" not in tokens
        assert "search" in tokens
        assert "file" in tokens
        assert "directory" in tokens

    def test_empty_string(self):
        assert _tokenize("") == []

    def test_mixed_separators(self):
        tokens = _tokenize("http-request_handler.v2")
        assert "http" in tokens
        assert "request" in tokens
        assert "handler" in tokens
        assert "v2" in tokens


# ---------------------------------------------------------------------------
# _BM25Index
# ---------------------------------------------------------------------------


class TestBM25Index:
    def test_empty_index(self):
        idx = _BM25Index()
        idx.build()
        assert idx.search("anything") == []

    def test_exact_match(self):
        idx = _BM25Index()
        idx.add("send_slack_message", "Send a message to a Slack channel", ["channel", "text"])
        idx.add("read_file", "Read contents of a file from disk", ["path"])
        idx.add("current_time", "Get the current date and time", ["timezone"])
        idx.build()

        results = idx.search("slack")
        assert len(results) >= 1
        assert results[0][0] == "send_slack_message"

    def test_description_match(self):
        idx = _BM25Index()
        idx.add("web_fetch", "Download a web page and return its content", ["url"])
        idx.add("read_file", "Read a local file from disk", ["path"])
        idx.build()

        results = idx.search("download web page")
        assert len(results) >= 1
        assert results[0][0] == "web_fetch"

    def test_param_match(self):
        idx = _BM25Index()
        idx.add("send_email", "Send an electronic message", ["recipient", "subject", "body"])
        idx.add("write_file", "Write content to disk", ["path", "content"])
        idx.build()

        results = idx.search("recipient subject")
        assert len(results) >= 1
        assert results[0][0] == "send_email"

    def test_max_results_limit(self):
        idx = _BM25Index()
        for i in range(10):
            idx.add(f"tool_{i}", f"A tool that does thing {i}", [])
        idx.build()

        results = idx.search("tool", max_results=3)
        assert len(results) == 3

    def test_threshold_filtering(self):
        idx = _BM25Index()
        idx.add("send_slack_message", "Send a Slack message", ["channel"])
        idx.add("read_file", "Read a file", ["path"])
        idx.build()

        # With a very high threshold, nothing should match
        results = idx.search("slack", threshold=999.0)
        assert results == []

    def test_prefix_matching(self):
        idx = _BM25Index()
        idx.add("send_notification", "Send a push notification", ["device_id"])
        idx.add("read_file", "Read a file", ["path"])
        idx.build()

        # "notif" is a prefix of "notification"
        results = idx.search("notif")
        assert len(results) >= 1
        assert results[0][0] == "send_notification"

    def test_no_match(self):
        idx = _BM25Index()
        idx.add("read_file", "Read a file from disk", ["path"])
        idx.build()

        results = idx.search("xyznonexistent")
        assert results == []

    def test_empty_query(self):
        idx = _BM25Index()
        idx.add("read_file", "Read a file", ["path"])
        idx.build()

        results = idx.search("")
        assert results == []


# ---------------------------------------------------------------------------
# ToolSearchManager
# ---------------------------------------------------------------------------


class TestToolSearchManager:
    def _sample_tool_defs(self):
        return [
            _make_tool_def("search_tools", "Search for tools"),
            _make_tool_def(
                "send_slack_message",
                "Send a message to Slack",
                {"type": "object", "properties": {"channel": {}, "text": {}}},
            ),
            _make_tool_def("read_file", "Read a file from disk"),
            _make_tool_def("current_time", "Get current date and time"),
            _make_tool_def("write_file", "Write content to a file"),
            _make_tool_def("web_search", "Search the web"),
        ]

    def test_prepare_tools_hides_non_discovered(self):
        manager = ToolSearchManager(always_available=["current_time"])
        tool_defs = self._sample_tool_defs()

        ctx = MagicMock()
        visible = asyncio.run(manager.prepare_tools_callback(ctx, tool_defs))

        visible_names = {td.name for td in visible}
        # Should see: search_tools (meta-tool) + current_time (always_available)
        assert "search_tools" in visible_names
        assert "current_time" in visible_names
        # Should NOT see: hidden tools
        assert "send_slack_message" not in visible_names
        assert "read_file" not in visible_names

    def test_search_makes_tools_visible(self):
        manager = ToolSearchManager(always_available=[])
        tool_defs = self._sample_tool_defs()

        ctx = MagicMock()
        # Build catalog first
        asyncio.run(manager.prepare_tools_callback(ctx, tool_defs))

        # Search for slack
        result = manager.search("slack message")
        assert "send_slack_message" in result

        # Now prepare_tools should include the discovered tool
        visible = asyncio.run(manager.prepare_tools_callback(ctx, tool_defs))
        visible_names = {td.name for td in visible}
        assert "send_slack_message" in visible_names

    def test_always_available_bypass(self):
        manager = ToolSearchManager(always_available=["current_time", "web_search"])
        tool_defs = self._sample_tool_defs()

        ctx = MagicMock()
        visible = asyncio.run(manager.prepare_tools_callback(ctx, tool_defs))

        visible_names = {td.name for td in visible}
        assert "current_time" in visible_names
        assert "web_search" in visible_names

    def test_runtime_tools_pass_through(self):
        """Tools not in the original catalog (e.g. runtime-added) pass through."""
        manager = ToolSearchManager(always_available=[])
        tool_defs = self._sample_tool_defs()

        ctx = MagicMock()
        asyncio.run(manager.prepare_tools_callback(ctx, tool_defs))

        # Add a runtime tool not in the original catalog
        runtime_tool = _make_tool_def("reflect_on_progress", "Reflect on task progress")
        extended_defs = [*tool_defs, runtime_tool]

        visible = asyncio.run(manager.prepare_tools_callback(ctx, extended_defs))
        visible_names = {td.name for td in visible}
        assert "reflect_on_progress" in visible_names

    def test_reset_discovered(self):
        manager = ToolSearchManager(always_available=[])
        tool_defs = self._sample_tool_defs()

        ctx = MagicMock()
        asyncio.run(manager.prepare_tools_callback(ctx, tool_defs))

        # Discover a tool
        manager.search("slack")

        # Reset
        manager.reset_discovered()

        # Tool should be hidden again
        visible = asyncio.run(manager.prepare_tools_callback(ctx, tool_defs))
        visible_names = {td.name for td in visible}
        assert "send_slack_message" not in visible_names

    def test_search_before_catalog_init(self):
        manager = ToolSearchManager(always_available=[])
        result = manager.search("anything")
        assert "not yet initialised" in result

    def test_thread_safety(self):
        """Concurrent searches should not corrupt state."""
        manager = ToolSearchManager(always_available=[])
        tool_defs = self._sample_tool_defs()

        ctx = MagicMock()
        asyncio.run(manager.prepare_tools_callback(ctx, tool_defs))

        errors: list[Exception] = []

        def search_worker(query: str):
            try:
                for _ in range(20):
                    manager.search(query)
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=search_worker, args=("slack",)),
            threading.Thread(target=search_worker, args=("file",)),
            threading.Thread(target=search_worker, args=("web",)),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"Concurrent search errors: {errors}"


# ---------------------------------------------------------------------------
# build_tool_search_toolset
# ---------------------------------------------------------------------------


class TestBuildToolSearchToolset:
    def test_toolset_has_search_tools(self):
        manager = ToolSearchManager(always_available=[])
        toolset = build_tool_search_toolset(manager)
        # FunctionToolset registers tools; verify it builds without error
        assert toolset is not None


# ---------------------------------------------------------------------------
# ToolSearchConfig schema
# ---------------------------------------------------------------------------


class TestToolSearchConfig:
    def test_defaults(self):
        config = ToolSearchConfig()
        assert config.enabled is False
        assert config.always_available == []
        assert config.max_results == 5
        assert config.threshold == 0.0

    def test_custom_values(self):
        config = ToolSearchConfig(
            enabled=True,
            always_available=["current_time", "search_documents"],
            max_results=10,
            threshold=0.5,
        )
        assert config.enabled is True
        assert config.always_available == ["current_time", "search_documents"]
        assert config.max_results == 10
        assert config.threshold == 0.5

    def test_max_results_bounds(self):
        with pytest.raises(ValidationError):
            ToolSearchConfig(max_results=0)
        with pytest.raises(ValidationError):
            ToolSearchConfig(max_results=21)

    def test_threshold_non_negative(self):
        with pytest.raises(ValidationError):
            ToolSearchConfig(threshold=-1.0)

    def test_role_definition_default(self):
        role = RoleDefinition.model_validate(_minimal_role_data())
        assert role.spec.tool_search.enabled is False

    def test_role_definition_with_tool_search(self):
        data = _minimal_role_data(
            tool_search={
                "enabled": True,
                "always_available": ["current_time"],
                "max_results": 8,
            }
        )
        role = RoleDefinition.model_validate(data)
        assert role.spec.tool_search.enabled is True
        assert role.spec.tool_search.always_available == ["current_time"]
        assert role.spec.tool_search.max_results == 8


# ---------------------------------------------------------------------------
# Integration: build_agent with tool_search enabled
# ---------------------------------------------------------------------------


class TestBuildAgentIntegration:
    def test_build_agent_with_tool_search(self, monkeypatch):
        """build_agent with tool_search.enabled produces an agent with prepare_tools."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

        from initrunner.agent.loader import build_agent

        data = _minimal_role_data(
            tool_search={"enabled": True, "always_available": ["current_time"]},
            tools=[{"type": "datetime"}],
        )
        role = RoleDefinition.model_validate(data)
        agent = build_agent(role)

        # Agent should have _prepare_tools set (non-None)
        assert agent._prepare_tools is not None

    def test_build_agent_without_tool_search(self, monkeypatch):
        """build_agent without tool_search leaves prepare_tools as None."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

        from initrunner.agent.loader import build_agent

        data = _minimal_role_data()
        role = RoleDefinition.model_validate(data)
        agent = build_agent(role)

        assert agent._prepare_tools is None
