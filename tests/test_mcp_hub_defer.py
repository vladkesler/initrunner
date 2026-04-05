"""Tests for MCP Hub defer aggregation and cache invalidation endpoint."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from unittest.mock import MagicMock

from initrunner.agent.schema.security import ToolSandboxConfig
from initrunner.agent.schema.tools import McpToolConfig
from initrunner.services.mcp_hub import aggregate_mcp_servers

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_role(
    name: str,
    mcp_configs: list[McpToolConfig],
    *,
    sandbox: ToolSandboxConfig | None = None,
):
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
# Mixed defer aggregation
# ---------------------------------------------------------------------------


class TestMixedDeferAggregation:
    def test_same_server_different_defer(self):
        """Same MCP server used by two agents, one deferred and one eager."""
        cfg_eager = McpToolConfig(transport="stdio", command="npx", args=["@mcp/server-fs", "/tmp"])
        cfg_deferred = McpToolConfig(
            transport="stdio", command="npx", args=["@mcp/server-fs", "/tmp"], defer=True
        )

        role_a = _make_role("agent-a", [cfg_eager])
        role_b = _make_role("agent-b", [cfg_deferred])

        cache = _make_role_cache(
            {
                "a": FakeDiscovered(path=Path("/roles/a.yaml"), role=role_a),
                "b": FakeDiscovered(path=Path("/roles/b.yaml"), role=role_b),
            }
        )

        servers = aggregate_mcp_servers(cache)
        assert len(servers) == 1  # same server, deduplicated

        entry = servers[0]
        assert len(entry.agent_refs) == 2

        # One ref should be deferred, the other not.
        defer_values = {r.agent_name: r.defer for r in entry.agent_refs}
        assert defer_values["agent-a"] is False
        assert defer_values["agent-b"] is True

    def test_defer_field_propagated(self):
        cfg = McpToolConfig(transport="stdio", command="echo", args=["hi"], defer=True)
        role = _make_role("my-agent", [cfg])
        cache = _make_role_cache(
            {
                "x": FakeDiscovered(path=Path("/roles/x.yaml"), role=role),
            }
        )

        servers = aggregate_mcp_servers(cache)
        assert len(servers) == 1
        assert servers[0].agent_refs[0].defer is True
