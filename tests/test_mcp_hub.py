"""Tests for the MCP Hub service layer."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from initrunner.agent.schema.security import ToolSandboxConfig
from initrunner.agent.schema.tools import McpToolConfig
from initrunner.services.mcp_hub import (
    AgentRef,
    McpServerEntry,
    _server_identity_hash,
    aggregate_mcp_servers,
    find_server,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_role(
    name: str,
    mcp_configs: list[McpToolConfig],
    *,
    sandbox: ToolSandboxConfig | None = None,
):
    """Build a minimal mock role with the given MCP tool configs."""
    role = MagicMock()
    role.metadata.name = name
    role.spec.tools = mcp_configs
    role.spec.security.tools = sandbox or ToolSandboxConfig()
    return role


@dataclass
class FakeDiscovered:
    path: Path
    role: object | None = None
    error: str | None = None


def _make_role_cache(entries: dict[str, FakeDiscovered]) -> MagicMock:
    cache = MagicMock()
    cache.all.return_value = entries
    return cache


# ---------------------------------------------------------------------------
# Identity hashing
# ---------------------------------------------------------------------------


class TestServerIdentityHash:
    def test_same_config_same_hash(self):
        a = McpToolConfig(transport="stdio", command="npx", args=["@mcp/server-fs", "/tmp"])
        b = McpToolConfig(transport="stdio", command="npx", args=["@mcp/server-fs", "/tmp"])
        assert _server_identity_hash(a) == _server_identity_hash(b)

    def test_different_command_different_hash(self):
        a = McpToolConfig(transport="stdio", command="npx", args=["@mcp/server-fs"])
        b = McpToolConfig(transport="stdio", command="uvx", args=["@mcp/server-fs"])
        assert _server_identity_hash(a) != _server_identity_hash(b)

    def test_different_cwd_different_hash(self):
        a = McpToolConfig(transport="stdio", command="npx", args=["test"], cwd="/a")
        b = McpToolConfig(transport="stdio", command="npx", args=["test"], cwd="/b")
        assert _server_identity_hash(a) != _server_identity_hash(b)

    def test_different_env_keys_different_hash(self):
        a = McpToolConfig(transport="stdio", command="npx", args=["test"], env={"FOO": "1"})
        b = McpToolConfig(transport="stdio", command="npx", args=["test"], env={"BAR": "1"})
        assert _server_identity_hash(a) != _server_identity_hash(b)

    def test_different_headers_different_hash(self):
        a = McpToolConfig(transport="sse", url="http://x", headers={"Auth": "a"})
        b = McpToolConfig(transport="sse", url="http://x", headers={"Auth": "b"})
        assert _server_identity_hash(a) != _server_identity_hash(b)

    def test_filter_excluded_from_hash(self):
        """tool_filter/tool_exclude/tool_prefix are per-agent, not identity."""
        a = McpToolConfig(transport="stdio", command="npx", args=["test"], tool_filter=["a", "b"])
        b = McpToolConfig(transport="stdio", command="npx", args=["test"], tool_exclude=["c"])
        assert _server_identity_hash(a) == _server_identity_hash(b)

    def test_timeout_excluded_from_hash(self):
        a = McpToolConfig(transport="stdio", command="npx", args=["t"], timeout_seconds=10)
        b = McpToolConfig(transport="stdio", command="npx", args=["t"], timeout_seconds=60)
        assert _server_identity_hash(a) == _server_identity_hash(b)


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


class TestAggregation:
    def test_deduplicates_same_server(self):
        cfg = McpToolConfig(transport="stdio", command="npx", args=["@mcp/server-fs"])
        role_a = _make_role("agent-a", [cfg])
        role_b = _make_role("agent-b", [cfg])
        cache = _make_role_cache(
            {
                "id-a": FakeDiscovered(path=Path("/a/role.yaml"), role=role_a),
                "id-b": FakeDiscovered(path=Path("/b/role.yaml"), role=role_b),
            }
        )
        result = aggregate_mcp_servers(cache)
        assert len(result) == 1
        assert len(result[0].agent_refs) == 2
        names = {r.agent_name for r in result[0].agent_refs}
        assert names == {"agent-a", "agent-b"}

    def test_separates_different_servers(self):
        cfg_a = McpToolConfig(transport="stdio", command="npx", args=["server-a"])
        cfg_b = McpToolConfig(transport="sse", url="http://localhost:8080")
        role = _make_role("agent", [cfg_a, cfg_b])
        cache = _make_role_cache({"id": FakeDiscovered(path=Path("/r/role.yaml"), role=role)})
        result = aggregate_mcp_servers(cache)
        assert len(result) == 2

    def test_skips_errored_roles(self):
        cache = _make_role_cache(
            {"id": FakeDiscovered(path=Path("/x/role.yaml"), role=None, error="bad yaml")}
        )
        result = aggregate_mcp_servers(cache)
        assert len(result) == 0

    def test_preserves_sandbox(self):
        sandbox = ToolSandboxConfig(mcp_command_allowlist=["npx"])
        cfg = McpToolConfig(transport="stdio", command="npx", args=["test"])
        role = _make_role("agent", [cfg], sandbox=sandbox)
        cache = _make_role_cache({"id": FakeDiscovered(path=Path("/r/role.yaml"), role=role)})
        result = aggregate_mcp_servers(cache)
        assert result[0].sandbox is not None
        assert result[0].sandbox.mcp_command_allowlist == ["npx"]

    def test_preserves_per_agent_filters_as_refs(self):
        cfg = McpToolConfig(
            transport="stdio",
            command="npx",
            args=["test"],
            tool_filter=["read_file"],
            tool_prefix="fs",
        )
        role = _make_role("agent", [cfg])
        cache = _make_role_cache({"id": FakeDiscovered(path=Path("/r/role.yaml"), role=role)})
        result = aggregate_mcp_servers(cache)
        ref = result[0].agent_refs[0]
        assert ref.tool_filter == ["read_file"]
        assert ref.tool_prefix == "fs"


class TestFindServer:
    def test_finds_by_id(self):
        cfg = McpToolConfig(transport="stdio", command="npx", args=["test"])
        role = _make_role("agent", [cfg])
        cache = _make_role_cache({"id": FakeDiscovered(path=Path("/r/role.yaml"), role=role)})
        entries = aggregate_mcp_servers(cache)
        sid = entries[0].server_id
        found = find_server(sid, cache)
        assert found is not None
        assert found.server_id == sid

    def test_returns_none_for_missing(self):
        cache = _make_role_cache({})
        assert find_server("nonexistent", cache) is None
