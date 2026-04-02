"""Tests for the MCP gateway (initrunner.mcp.gateway)."""

from __future__ import annotations

import asyncio
import textwrap
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from initrunner.mcp.gateway import (
    _VALID_TRANSPORTS,
    _AgentEntry,
    _make_tool_name,
    _register_agent_tool,
    _register_pass_through_tools,
    build_mcp_gateway,
    run_mcp_gateway,
)

runner = CliRunner()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_MINIMAL_ROLE_YAML = textwrap.dedent("""\
    apiVersion: initrunner/v1
    kind: Agent
    metadata:
      name: {name}
      description: "{description}"
    spec:
      role: You are helpful.
      model:
        provider: openai
        name: gpt-5-mini
""")


def _write_role(tmp_path: Path, name: str, description: str = "A test agent") -> Path:
    role_file = tmp_path / f"{name}.yaml"
    role_file.write_text(_MINIMAL_ROLE_YAML.format(name=name, description=description))
    return role_file


def _make_entry(name: str, description: str = "A test agent") -> _AgentEntry:
    role = MagicMock()
    role.metadata.name = name
    role.metadata.description = description
    role.spec.tools = []
    agent = MagicMock()
    return _AgentEntry(
        name=name,
        description=description,
        role=role,
        agent=agent,
        role_path=Path(f"/tmp/{name}.yaml"),
    )


@dataclass
class _FakeRunResult:
    success: bool = True
    output: str = "hello"
    error: str | None = None


# ---------------------------------------------------------------------------
# TestMakeToolName
# ---------------------------------------------------------------------------


class TestMakeToolName:
    def test_simple_name(self):
        seen: set[str] = set()
        assert _make_tool_name("my-agent", seen) == "my-agent"
        assert "my-agent" in seen

    def test_uniqueness_suffix(self):
        seen: set[str] = set()
        assert _make_tool_name("agent", seen) == "agent"
        assert _make_tool_name("agent", seen) == "agent_2"
        assert _make_tool_name("agent", seen) == "agent_3"

    def test_sanitizes_special_chars(self):
        seen: set[str] = set()
        assert _make_tool_name("my agent!", seen) == "my_agent_"

    def test_empty_name_fallback(self):
        seen: set[str] = set()
        assert _make_tool_name("", seen) == "agent"

    def test_all_special_chars(self):
        seen: set[str] = set()
        result = _make_tool_name("!!!", seen)
        assert result == "___"


# ---------------------------------------------------------------------------
# TestBuildMcpGateway
# ---------------------------------------------------------------------------


class TestBuildMcpGateway:
    def test_empty_role_paths_raises(self):
        with pytest.raises(ValueError, match="At least one role file required"):
            build_mcp_gateway([])

    @patch("initrunner.mcp.gateway._load_agents")
    def test_single_role(self, mock_load):
        entry = _make_entry("greeter", "A greeter bot")
        mock_load.return_value = [entry]

        mcp = build_mcp_gateway([Path("/tmp/greeter.yaml")])
        assert mcp is not None
        # The gateway should have registered a tool
        mock_load.assert_called_once()

    @patch("initrunner.mcp.gateway._load_agents")
    def test_multiple_roles(self, mock_load):
        entries = [
            _make_entry("alpha", "Alpha agent"),
            _make_entry("beta", "Beta agent"),
        ]
        mock_load.return_value = entries

        mcp = build_mcp_gateway([Path("/tmp/a.yaml"), Path("/tmp/b.yaml")])
        assert mcp is not None

    @patch("initrunner.mcp.gateway._load_agents")
    def test_duplicate_names_get_suffixed(self, mock_load):
        entries = [
            _make_entry("agent", "First"),
            _make_entry("agent", "Second"),
        ]
        mock_load.return_value = entries

        mcp = build_mcp_gateway([Path("/tmp/a.yaml"), Path("/tmp/b.yaml")])
        assert mcp is not None

    @patch("initrunner.mcp.gateway._load_agents")
    def test_description_from_entry(self, mock_load):
        entry = _make_entry("helper", "Helps with things")
        mock_load.return_value = [entry]

        mcp = build_mcp_gateway([Path("/tmp/helper.yaml")])
        assert mcp is not None

    def test_role_load_failure(self):
        with patch(
            "initrunner.mcp.gateway._load_agents",
            side_effect=RuntimeError("Failed to load /bad.yaml: file not found"),
        ):
            with pytest.raises(RuntimeError, match=r"Failed to load /bad\.yaml"):
                build_mcp_gateway([Path("/bad.yaml")])


# ---------------------------------------------------------------------------
# TestAgentToolExecution
# ---------------------------------------------------------------------------


class TestAgentToolExecution:
    def test_success_returns_output(self):
        from fastmcp import FastMCP

        mcp = FastMCP("test")
        entry = _make_entry("bot", "A bot")

        with patch("initrunner.agent.executor.execute_run") as mock_exec:
            mock_exec.return_value = (_FakeRunResult(success=True, output="hi there"), [])
            _register_agent_tool(mcp, entry, "bot", None)
            # Call while patch is active (handler calls execute_run at invocation time)
            tool = asyncio.run(mcp.get_tool("bot"))
            assert tool is not None
            result = tool.fn(prompt="hello")  # type: ignore[unresolved-attribute]
            assert result == "hi there"

    def test_failure_returns_error_string(self):
        from fastmcp import FastMCP

        mcp = FastMCP("test")
        entry = _make_entry("bot", "A bot")

        with patch("initrunner.agent.executor.execute_run") as mock_exec:
            mock_exec.return_value = (
                _FakeRunResult(success=False, error="model overloaded"),
                [],
            )
            _register_agent_tool(mcp, entry, "bot", None)
            tool = asyncio.run(mcp.get_tool("bot"))
            result = tool.fn(prompt="hello")  # type: ignore[unresolved-attribute]
            assert result == "Error: model overloaded"

    def test_exception_caught(self):
        from fastmcp import FastMCP

        mcp = FastMCP("test")
        entry = _make_entry("bot", "A bot")

        with patch("initrunner.agent.executor.execute_run") as mock_exec:
            mock_exec.side_effect = RuntimeError("boom")
            _register_agent_tool(mcp, entry, "bot", None)
            tool = asyncio.run(mcp.get_tool("bot"))
            result = tool.fn(prompt="hello")  # type: ignore[unresolved-attribute]
            assert "Internal error" in result
            assert "boom" in result

    def test_closure_correctness(self):
        """Register 3 agents and verify each tool calls the right one."""
        from fastmcp import FastMCP

        mcp = FastMCP("test")

        entries = [
            _make_entry("alpha", "Alpha"),
            _make_entry("beta", "Beta"),
            _make_entry("gamma", "Gamma"),
        ]

        with patch("initrunner.agent.executor.execute_run") as mock_exec:

            def side_effect(agent, role, prompt, **kwargs):
                # Return which agent name was used
                return _FakeRunResult(success=True, output=f"from:{role.metadata.name}"), []

            mock_exec.side_effect = side_effect

            seen: set[str] = set()
            for entry in entries:
                tool_name = _make_tool_name(entry.name, seen)
                _register_agent_tool(mcp, entry, tool_name, None)

            for name in ("alpha", "beta", "gamma"):
                tool = asyncio.run(mcp.get_tool(name))
                assert tool.fn(prompt="x") == f"from:{name}"  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# TestRunMcpGateway
# ---------------------------------------------------------------------------


class TestRunMcpGateway:
    def test_stdio_transport(self):
        mcp = MagicMock()
        run_mcp_gateway(mcp, transport="stdio")
        mcp.run.assert_called_once_with(transport="stdio", show_banner=False)

    def test_sse_transport(self):
        mcp = MagicMock()
        run_mcp_gateway(mcp, transport="sse", host="0.0.0.0", port=9090)
        mcp.run.assert_called_once_with(transport="sse", host="0.0.0.0", port=9090)

    def test_streamable_http_transport(self):
        mcp = MagicMock()
        run_mcp_gateway(mcp, transport="streamable-http", host="localhost", port=3000)
        mcp.run.assert_called_once_with(transport="streamable-http", host="localhost", port=3000)

    def test_invalid_transport_raises(self):
        mcp = MagicMock()
        with pytest.raises(ValueError, match="Unknown transport"):
            run_mcp_gateway(mcp, transport="grpc")

    def test_valid_transports_set(self):
        assert _VALID_TRANSPORTS == {"stdio", "sse", "streamable-http"}


# ---------------------------------------------------------------------------
# TestMcpServeCli
# ---------------------------------------------------------------------------


class TestMcpServeCli:
    def test_serve_help(self):
        import re

        from initrunner.cli.main import app

        result = runner.invoke(app, ["mcp", "serve", "--help"])
        assert result.exit_code == 0
        plain = re.sub(r"\x1b\[[0-9;]*m", "", result.output)
        assert "serve" in plain.lower()
        assert "--transport" in plain

    def test_serve_invalid_transport(self, tmp_path):
        from initrunner.cli.main import app

        role_file = _write_role(tmp_path, "test")
        result = runner.invoke(app, ["mcp", "serve", str(role_file), "--transport", "grpc"])
        assert result.exit_code == 1

    def test_serve_missing_file(self):
        from initrunner.cli.main import app

        result = runner.invoke(app, ["mcp", "serve", "/nonexistent/role.yaml"])
        assert result.exit_code == 1

    @patch("initrunner.mcp.gateway.run_mcp_gateway")
    @patch("initrunner.mcp.gateway.build_mcp_gateway")
    def test_serve_wiring(self, mock_build, mock_run, tmp_path):
        from initrunner.cli.main import app

        role_file = _write_role(tmp_path, "test")
        mock_build.return_value = MagicMock()

        result = runner.invoke(app, ["mcp", "serve", str(role_file)])
        assert result.exit_code == 0
        mock_build.assert_called_once()
        mock_run.assert_called_once()

        # Verify transport default
        call_kwargs = mock_run.call_args
        assert call_kwargs[1]["transport"] == "stdio"


# ---------------------------------------------------------------------------
# TestPassThroughTools
# ---------------------------------------------------------------------------


class TestPassThroughTools:
    """Tests for _register_pass_through_tools with fastmcp 3.x APIs."""

    def _make_entry_with_mcp(
        self, name: str, *, tool_filter=None, tool_exclude=None, tool_prefix=None
    ) -> _AgentEntry:
        from initrunner.agent.schema.tools import McpToolConfig

        cfg = McpToolConfig(
            type="mcp",
            transport="stdio",
            command="echo",
            tool_filter=tool_filter or [],
            tool_exclude=tool_exclude or [],
            tool_prefix=tool_prefix,
        )
        role = MagicMock()
        role.metadata.name = name
        role.metadata.description = f"{name} agent"
        role.spec.tools = [cfg]
        role.spec.security.tools = MagicMock()
        agent = MagicMock()
        return _AgentEntry(
            name=name, description=f"{name} agent", role=role, agent=agent,
            role_path=Path(f"/tmp/{name}.yaml"),
        )

    @patch("initrunner.mcp.gateway._build_pass_through_transport")
    def test_basic_mount(self, mock_transport):
        """Pass-through with no filter/exclude mounts a proxy with agent namespace."""
        from fastmcp import FastMCP

        source = FastMCP("source")

        @source.tool
        def greet(name: str) -> str:
            return f"hi {name}"

        mock_transport.return_value = source

        parent = FastMCP("parent")
        entries = [self._make_entry_with_mcp("bot")]
        _register_pass_through_tools(parent, entries)

        tools = asyncio.run(parent.list_tools())
        tool_names = {t.name for t in tools}
        assert "bot_greet" in tool_names

    @patch("initrunner.mcp.gateway._build_pass_through_transport")
    def test_tool_filter_allowlist(self, mock_transport):
        """Only tools in tool_filter should be visible."""
        from fastmcp import FastMCP

        source = FastMCP("source")

        @source.tool
        def allowed_tool() -> str:
            return "ok"

        @source.tool
        def hidden_tool() -> str:
            return "nope"

        mock_transport.return_value = source

        parent = FastMCP("parent")
        entries = [self._make_entry_with_mcp("bot", tool_filter=["allowed_tool"])]
        _register_pass_through_tools(parent, entries)

        tools = asyncio.run(parent.list_tools())
        tool_names = {t.name for t in tools}
        assert "bot_allowed_tool" in tool_names
        assert "bot_hidden_tool" not in tool_names

    @patch("initrunner.mcp.gateway._build_pass_through_transport")
    def test_tool_exclude_blocklist(self, mock_transport):
        """Tools in tool_exclude should be hidden."""
        from fastmcp import FastMCP

        source = FastMCP("source")

        @source.tool
        def keep_me() -> str:
            return "ok"

        @source.tool
        def drop_me() -> str:
            return "nope"

        mock_transport.return_value = source

        parent = FastMCP("parent")
        entries = [self._make_entry_with_mcp("bot", tool_exclude=["drop_me"])]
        _register_pass_through_tools(parent, entries)

        tools = asyncio.run(parent.list_tools())
        tool_names = {t.name for t in tools}
        assert "bot_keep_me" in tool_names
        assert "bot_drop_me" not in tool_names

    @patch("initrunner.mcp.gateway._build_pass_through_transport")
    def test_tool_prefix(self, mock_transport):
        """Custom tool_prefix is appended to the agent namespace."""
        from fastmcp import FastMCP

        source = FastMCP("source")

        @source.tool
        def ping() -> str:
            return "pong"

        mock_transport.return_value = source

        parent = FastMCP("parent")
        entries = [self._make_entry_with_mcp("bot", tool_prefix="custom_")]
        _register_pass_through_tools(parent, entries)

        tools = asyncio.run(parent.list_tools())
        tool_names = {t.name for t in tools}
        assert "bot_custom_ping" in tool_names

    @patch("initrunner.mcp.gateway._build_pass_through_transport")
    def test_no_mcp_configs_skipped(self, mock_transport):
        """Entries without MCP tool configs are silently skipped."""
        from fastmcp import FastMCP

        parent = FastMCP("parent")
        entry = _make_entry("plain")  # no MCP tools
        _register_pass_through_tools(parent, [entry])

        mock_transport.assert_not_called()
        tools = asyncio.run(parent.list_tools())
        assert len(tools) == 0
