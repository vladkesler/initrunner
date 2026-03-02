"""Tests for initrunner.mcp._transport.build_transport."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from initrunner.agent.schema.security import ToolSandboxConfig
from initrunner.agent.schema.tools import McpToolConfig
from initrunner.mcp._transport import build_transport

# ---------------------------------------------------------------------------
# Stdio transport
# ---------------------------------------------------------------------------


def test_stdio_basic():
    config = McpToolConfig(transport="stdio", command="npx", args=["-y", "server"])
    transport = build_transport(config)
    assert transport.command == "npx"
    assert transport.args == ["-y", "server"]


def test_stdio_cwd_absolute():
    config = McpToolConfig(transport="stdio", command="node", cwd="/tmp/abs")
    transport = build_transport(config, role_dir=Path("/role"))
    assert transport.cwd == "/tmp/abs"


def test_stdio_cwd_relative_with_role_dir():
    config = McpToolConfig(transport="stdio", command="node", cwd="sub/dir")
    transport = build_transport(config, role_dir=Path("/project/roles"))
    assert transport.cwd == str(Path("/project/roles/sub/dir"))


def test_stdio_cwd_relative_no_role_dir():
    config = McpToolConfig(transport="stdio", command="node", cwd="sub/dir")
    transport = build_transport(config, role_dir=None)
    # Without role_dir, relative cwd is kept as-is
    assert transport.cwd == "sub/dir"


def test_stdio_env_scrubbed():
    config = McpToolConfig(transport="stdio", command="node")
    with patch.dict("os.environ", {"OPENAI_API_KEY": "secret", "HOME": "/home/test"}, clear=True):
        transport = build_transport(config)
    assert "OPENAI_API_KEY" not in transport.env
    assert transport.env.get("HOME") == "/home/test"


def test_stdio_env_scrubbed_with_sandbox():
    sandbox = ToolSandboxConfig(
        sensitive_env_prefixes=["CUSTOM_SECRET"],
        sensitive_env_suffixes=[],
        env_allowlist=[],
    )
    config = McpToolConfig(transport="stdio", command="node")
    with patch.dict(
        "os.environ",
        {"CUSTOM_SECRET_KEY": "hidden", "PATH": "/usr/bin"},
        clear=True,
    ):
        transport = build_transport(config, sandbox=sandbox)
    assert "CUSTOM_SECRET_KEY" not in transport.env


def test_stdio_env_vars_resolved():
    config = McpToolConfig(transport="stdio", command="node", env={"MY_VAR": "${TEST_RESOLVE}"})
    with patch.dict("os.environ", {"TEST_RESOLVE": "resolved_value"}, clear=True):
        transport = build_transport(config)
    assert transport.env["MY_VAR"] == "resolved_value"


def test_stdio_timeout_ignored():
    """StdioTransport does not support timeout — config.timeout is silently ignored."""
    config = McpToolConfig(transport="stdio", command="node", timeout=42)
    transport = build_transport(config)
    assert transport.command == "node"


# ---------------------------------------------------------------------------
# Command allowlist validation
# ---------------------------------------------------------------------------


def test_command_allowlist_blocks_unlisted():
    sandbox = ToolSandboxConfig(mcp_command_allowlist=["npx", "uvx"])
    config = McpToolConfig(transport="stdio", command="evil-cmd")
    with pytest.raises(ValueError, match="not in the allowed command list"):
        build_transport(config, sandbox=sandbox)


def test_command_allowlist_allows_listed():
    sandbox = ToolSandboxConfig(mcp_command_allowlist=["npx", "uvx"])
    config = McpToolConfig(transport="stdio", command="npx")
    transport = build_transport(config, sandbox=sandbox)
    assert transport.command == "npx"


def test_command_allowlist_empty_skips_validation():
    sandbox = ToolSandboxConfig(mcp_command_allowlist=[])
    config = McpToolConfig(transport="stdio", command="anything")
    transport = build_transport(config, sandbox=sandbox)
    assert transport.command == "anything"


def test_no_sandbox_skips_command_validation():
    config = McpToolConfig(transport="stdio", command="any-cmd")
    transport = build_transport(config, sandbox=None)
    assert transport.command == "any-cmd"


# ---------------------------------------------------------------------------
# SSE transport
# ---------------------------------------------------------------------------


def test_sse_basic():
    config = McpToolConfig(transport="sse", url="http://localhost:8080/sse")
    transport = build_transport(config)
    assert transport.url == "http://localhost:8080/sse"


def test_sse_with_headers():
    config = McpToolConfig(
        transport="sse",
        url="http://localhost:8080/sse",
        headers={"Authorization": "Bearer tok"},
    )
    transport = build_transport(config)
    assert transport.headers["Authorization"] == "Bearer tok"


def test_sse_timeout():
    config = McpToolConfig(transport="sse", url="http://localhost:8080/sse", timeout=30)
    transport = build_transport(config)
    from datetime import timedelta

    assert transport.sse_read_timeout == timedelta(seconds=30)


# ---------------------------------------------------------------------------
# Streamable HTTP transport
# ---------------------------------------------------------------------------


def test_streamable_http_basic():
    config = McpToolConfig(transport="streamable-http", url="http://localhost:9090/mcp")
    transport = build_transport(config)
    assert transport.url == "http://localhost:9090/mcp"


def test_streamable_http_with_headers():
    config = McpToolConfig(
        transport="streamable-http",
        url="http://localhost:9090/mcp",
        headers={"X-Custom": "val"},
    )
    transport = build_transport(config)
    assert transport.headers["X-Custom"] == "val"


# ---------------------------------------------------------------------------
# Unknown transport
# ---------------------------------------------------------------------------


def test_unknown_transport():
    config = McpToolConfig.__new__(McpToolConfig)
    object.__setattr__(config, "transport", "grpc")
    object.__setattr__(config, "headers", {})
    with pytest.raises(ValueError, match="Unknown MCP transport: grpc"):
        build_transport(config)


# ---------------------------------------------------------------------------
# Header env var resolution
# ---------------------------------------------------------------------------


def test_header_env_var_resolution():
    config = McpToolConfig(
        transport="sse",
        url="http://localhost/sse",
        headers={"Authorization": "Bearer ${MY_TOKEN}"},
    )
    with patch.dict("os.environ", {"MY_TOKEN": "secret123"}):
        transport = build_transport(config)
    assert transport.headers["Authorization"] == "Bearer secret123"
