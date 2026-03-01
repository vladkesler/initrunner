"""Tests for the MCP gateway (initrunner.mcp.gateway)."""

from __future__ import annotations

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
            tools = mcp._tool_manager._tools
            assert "bot" in tools
            result = tools["bot"].fn(prompt="hello")  # type: ignore[unresolved-attribute]
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
            result = mcp._tool_manager._tools["bot"].fn(prompt="hello")  # type: ignore[unresolved-attribute]
            assert result == "Error: model overloaded"

    def test_exception_caught(self):
        from fastmcp import FastMCP

        mcp = FastMCP("test")
        entry = _make_entry("bot", "A bot")

        with patch("initrunner.agent.executor.execute_run") as mock_exec:
            mock_exec.side_effect = RuntimeError("boom")
            _register_agent_tool(mcp, entry, "bot", None)
            result = mcp._tool_manager._tools["bot"].fn(prompt="hello")  # type: ignore[unresolved-attribute]
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

            tools = mcp._tool_manager._tools
            assert tools["alpha"].fn(prompt="x")  # type: ignore[unresolved-attribute] == "from:alpha"
            assert tools["beta"].fn(prompt="x")  # type: ignore[unresolved-attribute] == "from:beta"
            assert tools["gamma"].fn(prompt="x")  # type: ignore[unresolved-attribute] == "from:gamma"


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
