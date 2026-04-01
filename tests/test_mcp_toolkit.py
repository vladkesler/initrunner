"""Tests for the MCP toolkit (initrunner.mcp.toolkit)."""

from __future__ import annotations

import asyncio
import re
import textwrap
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from initrunner.mcp.toolkit import (
    _ALL_TOOLS,
    _DEFAULT_TOOLS,
    _TOOLKIT_REGISTRARS,
    ToolkitConfig,
    ToolkitCsvAnalysisConfig,
    ToolkitDatetimeConfig,
    ToolkitHttpConfig,
    ToolkitSearchConfig,
    ToolkitSqlConfig,
    ToolkitWebReaderConfig,
    build_toolkit,
    load_toolkit_config,
)

runner = CliRunner()


def _get_tool_names(mcp):  # type: ignore[no-untyped-def]
    """Get the set of registered tool names from a FastMCP instance."""
    tools = asyncio.run(mcp.list_tools())
    return {t.name for t in tools}


def _get_tool_fn(mcp, name):  # type: ignore[no-untyped-def]
    """Extract a tool function from a FastMCP instance by name."""
    tool = asyncio.run(mcp.get_tool(name))
    return tool.fn


# ---------------------------------------------------------------------------
# TestToolkitConfig
# ---------------------------------------------------------------------------


class TestToolkitConfig:
    def test_default_config(self):
        cfg = ToolkitConfig()
        assert cfg.server_name == "initrunner-toolkit"
        assert cfg.tools == {}

    def test_custom_server_name(self):
        cfg = ToolkitConfig(server_name="my-tools")
        assert cfg.server_name == "my-tools"

    def test_config_with_tools(self):
        cfg = ToolkitConfig(
            tools={
                "search": {"provider": "duckduckgo"},
                "datetime": {"default_timezone": "America/New_York"},
            }
        )
        assert "search" in cfg.tools
        assert "datetime" in cfg.tools

    def test_search_config_defaults(self):
        cfg = ToolkitSearchConfig()
        assert cfg.provider == "duckduckgo"
        assert cfg.api_key == ""
        assert cfg.max_results == 10
        assert cfg.safe_search is True

    def test_web_reader_config_defaults(self):
        cfg = ToolkitWebReaderConfig()
        assert cfg.timeout_seconds == 15
        assert cfg.max_bytes == 512_000

    def test_csv_analysis_config_defaults(self):
        cfg = ToolkitCsvAnalysisConfig()
        assert cfg.root_path == "."
        assert cfg.max_rows == 1000

    def test_datetime_config_defaults(self):
        cfg = ToolkitDatetimeConfig()
        assert cfg.default_timezone == "UTC"

    def test_sql_config_requires_database(self):
        with pytest.raises(ValidationError):
            ToolkitSqlConfig()  # type: ignore[call-arg]

    def test_http_config_requires_base_url(self):
        with pytest.raises(ValidationError):
            ToolkitHttpConfig()  # type: ignore[call-arg]

    def test_load_config_from_yaml(self, tmp_path):
        config_file = tmp_path / "toolkit.yaml"
        config_file.write_text(
            textwrap.dedent("""\
            server_name: test-toolkit
            tools:
              search:
                provider: duckduckgo
              datetime:
                default_timezone: America/New_York
            """)
        )
        cfg = load_toolkit_config(config_file)
        assert cfg.server_name == "test-toolkit"
        assert "search" in cfg.tools
        assert cfg.tools["datetime"]["default_timezone"] == "America/New_York"

    def test_load_config_env_var_interpolation(self, tmp_path, monkeypatch):
        monkeypatch.setenv("TEST_DB_PATH", "/data/test.db")
        config_file = tmp_path / "toolkit.yaml"
        config_file.write_text(
            textwrap.dedent("""\
            tools:
              sql:
                database: ${TEST_DB_PATH}
            """)
        )
        cfg = load_toolkit_config(config_file)
        assert cfg.tools["sql"]["database"] == "/data/test.db"

    def test_load_config_empty_file(self, tmp_path):
        config_file = tmp_path / "toolkit.yaml"
        config_file.write_text("")
        cfg = load_toolkit_config(config_file)
        assert cfg.server_name == "initrunner-toolkit"
        assert cfg.tools == {}


# ---------------------------------------------------------------------------
# TestBuildToolkit
# ---------------------------------------------------------------------------


class TestBuildToolkit:
    def test_default_tools_registered(self):
        mcp = build_toolkit()
        tool_names = _get_tool_names(mcp)
        # Should have default tool functions registered
        assert len(tool_names) > 0

    def test_default_tools_include_expected(self):
        mcp = build_toolkit()
        tool_names = _get_tool_names(mcp)
        # search registers web_search and news_search
        assert "web_search" in tool_names
        assert "news_search" in tool_names
        # web_reader registers fetch_page
        assert "fetch_page" in tool_names
        # csv registers inspect_csv, summarize_csv, query_csv
        assert "inspect_csv" in tool_names
        assert "summarize_csv" in tool_names
        assert "query_csv" in tool_names
        # datetime registers current_time, parse_date
        assert "current_time" in tool_names
        assert "parse_date" in tool_names

    def test_selective_tools(self):
        mcp = build_toolkit(tool_names=["search"])
        tool_names = _get_tool_names(mcp)
        assert "web_search" in tool_names
        assert "news_search" in tool_names
        # datetime should NOT be registered
        assert "current_time" not in tool_names

    def test_selective_tools_datetime_only(self):
        mcp = build_toolkit(tool_names=["datetime"])
        tool_names = _get_tool_names(mcp)
        assert "current_time" in tool_names
        assert "parse_date" in tool_names
        assert "web_search" not in tool_names

    def test_unknown_tool_raises(self):
        with pytest.raises(ValueError, match="Unknown toolkit tool"):
            build_toolkit(tool_names=["nonexistent"])

    def test_config_tools_override_defaults(self):
        cfg = ToolkitConfig(tools={"datetime": {}})
        mcp = build_toolkit(cfg)
        tool_names = _get_tool_names(mcp)
        assert "current_time" in tool_names
        # search should NOT be registered (not in config.tools)
        assert "web_search" not in tool_names

    def test_server_name_from_config(self):
        cfg = ToolkitConfig(server_name="my-custom-server")
        mcp = build_toolkit(cfg)
        assert mcp.name == "my-custom-server"

    def test_tool_names_override_config_tools(self):
        cfg = ToolkitConfig(tools={"datetime": {}, "search": {}})
        mcp = build_toolkit(cfg, tool_names=["datetime"])
        tool_names = _get_tool_names(mcp)
        assert "current_time" in tool_names
        assert "web_search" not in tool_names

    def test_sql_tool_registration(self, tmp_path):
        db_path = tmp_path / "test.db"
        db_path.touch()
        cfg = ToolkitConfig(tools={"sql": {"database": str(db_path)}})
        mcp = build_toolkit(cfg)
        tool_names = _get_tool_names(mcp)
        assert "sql_query" in tool_names

    def test_http_tool_registration(self):
        cfg = ToolkitConfig(tools={"http": {"base_url": "https://api.example.com"}})
        mcp = build_toolkit(cfg)
        tool_names = _get_tool_names(mcp)
        assert "http_request" in tool_names

    def test_all_registrars_exist(self):
        """Every tool in _ALL_TOOLS should have a registrar."""
        for tool_name in _ALL_TOOLS:
            assert tool_name in _TOOLKIT_REGISTRARS

    def test_default_tools_set(self):
        assert _DEFAULT_TOOLS == {"search", "web_reader", "csv_analysis", "datetime"}


# ---------------------------------------------------------------------------
# TestToolExecution
# ---------------------------------------------------------------------------


class TestToolExecution:
    def test_current_time(self):
        mcp = build_toolkit(tool_names=["datetime"])
        fn = _get_tool_fn(mcp, "current_time")
        result = fn(tz="UTC")
        assert "UTC" in result
        # Should contain a date-like string
        assert re.search(r"\d{4}-\d{2}-\d{2}", result)

    def test_current_time_with_timezone(self):
        mcp = build_toolkit(tool_names=["datetime"])
        fn = _get_tool_fn(mcp, "current_time")
        result = fn(tz="America/New_York")
        assert "E" in result  # EST or EDT

    def test_current_time_invalid_timezone(self):
        mcp = build_toolkit(tool_names=["datetime"])
        fn = _get_tool_fn(mcp, "current_time")
        result = fn(tz="Invalid/Timezone")
        assert "Error" in result

    def test_parse_date(self):
        mcp = build_toolkit(tool_names=["datetime"])
        fn = _get_tool_fn(mcp, "parse_date")
        result = fn(date_string="2024-01-15")
        assert "2024-01-15" in result

    def test_parse_date_invalid(self):
        mcp = build_toolkit(tool_names=["datetime"])
        fn = _get_tool_fn(mcp, "parse_date")
        result = fn(date_string="not a date at all xyz")
        assert "Error" in result

    def test_inspect_csv(self, tmp_path):
        csv_file = tmp_path / "data.csv"
        csv_file.write_text("name,age,city\nAlice,30,NYC\nBob,25,LA\n")
        cfg = ToolkitConfig(tools={"csv_analysis": {"root_path": str(tmp_path)}})
        mcp = build_toolkit(cfg)
        fn = _get_tool_fn(mcp, "inspect_csv")
        result = fn(path="data.csv")
        assert "name" in result
        assert "age" in result
        assert "Alice" in result

    def test_inspect_csv_file_not_found(self, tmp_path):
        cfg = ToolkitConfig(tools={"csv_analysis": {"root_path": str(tmp_path)}})
        mcp = build_toolkit(cfg)
        fn = _get_tool_fn(mcp, "inspect_csv")
        result = fn(path="nonexistent.csv")
        assert "Error" in result

    def test_summarize_csv(self, tmp_path):
        csv_file = tmp_path / "data.csv"
        csv_file.write_text("name,score\nAlice,90\nBob,80\nCharlie,70\n")
        cfg = ToolkitConfig(tools={"csv_analysis": {"root_path": str(tmp_path)}})
        mcp = build_toolkit(cfg)
        fn = _get_tool_fn(mcp, "summarize_csv")
        result = fn(path="data.csv")
        assert "score" in result
        assert "numeric" in result

    def test_query_csv(self, tmp_path):
        csv_file = tmp_path / "data.csv"
        csv_file.write_text("name,age,city\nAlice,30,NYC\nBob,25,LA\nCharlie,35,NYC\n")
        cfg = ToolkitConfig(tools={"csv_analysis": {"root_path": str(tmp_path)}})
        mcp = build_toolkit(cfg)
        fn = _get_tool_fn(mcp, "query_csv")
        result = fn(path="data.csv", filter_column="city", filter_value="NYC")
        assert "Alice" in result
        assert "Charlie" in result

    def test_web_search(self):
        mock_fn = MagicMock(
            return_value=[
                {"title": "Test Result", "url": "https://example.com", "snippet": "A test."}
            ]
        )
        with patch.dict("initrunner.agent.tools.search._PROVIDERS", {"duckduckgo": mock_fn}):
            mcp = build_toolkit(tool_names=["search"])
            fn = _get_tool_fn(mcp, "web_search")
            result = fn(query="test")
        assert "Test Result" in result
        assert "https://example.com" in result

    def test_news_search(self):
        mock_fn = MagicMock(
            return_value=[
                {
                    "title": "Breaking News",
                    "url": "https://news.example.com",
                    "snippet": "Big news.",
                }
            ]
        )
        with patch.dict("initrunner.agent.tools.search._PROVIDERS", {"duckduckgo": mock_fn}):
            mcp = build_toolkit(tool_names=["search"])
            fn = _get_tool_fn(mcp, "news_search")
            result = fn(query="test")
        assert "Breaking News" in result

    @patch("initrunner._html.fetch_url_as_markdown")
    def test_fetch_page(self, mock_fetch):
        mock_fetch.return_value = "# Hello World\n\nThis is a test page."
        mcp = build_toolkit(tool_names=["web_reader"])
        fn = _get_tool_fn(mcp, "fetch_page")
        result = fn(url="https://example.com")
        assert "Hello World" in result

    def test_sql_query(self, tmp_path):
        import sqlite3

        db_path = tmp_path / "test.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE users (id INTEGER, name TEXT)")
        conn.execute("INSERT INTO users VALUES (1, 'Alice')")
        conn.execute("INSERT INTO users VALUES (2, 'Bob')")
        conn.commit()
        conn.close()

        cfg = ToolkitConfig(tools={"sql": {"database": str(db_path)}})
        mcp = build_toolkit(cfg)
        fn = _get_tool_fn(mcp, "sql_query")
        result = fn(query="SELECT * FROM users")
        assert "Alice" in result
        assert "Bob" in result

    def test_sql_read_only_blocks_writes(self, tmp_path):
        import sqlite3

        db_path = tmp_path / "test.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE users (id INTEGER, name TEXT)")
        conn.commit()
        conn.close()

        cfg = ToolkitConfig(tools={"sql": {"database": str(db_path), "read_only": True}})
        mcp = build_toolkit(cfg)
        fn = _get_tool_fn(mcp, "sql_query")
        result = fn(query="INSERT INTO users VALUES (1, 'Alice')")
        assert "Error" in result
        assert "read-only" in result

    def test_http_request_blocked_method(self):
        cfg = ToolkitConfig(
            tools={"http": {"base_url": "https://api.example.com", "allowed_methods": ["GET"]}}
        )
        mcp = build_toolkit(cfg)
        fn = _get_tool_fn(mcp, "http_request")
        result = fn(method="DELETE", path="/users/1")
        assert "Error" in result
        assert "not allowed" in result


# ---------------------------------------------------------------------------
# TestToolkitCli
# ---------------------------------------------------------------------------


class TestToolkitCli:
    def test_toolkit_help(self):
        from initrunner.cli.main import app

        result = runner.invoke(app, ["mcp", "toolkit", "--help"])
        assert result.exit_code == 0
        plain = re.sub(r"\x1b\[[0-9;]*m", "", result.output)
        assert "toolkit" in plain.lower()
        assert "--tools" in plain
        assert "--config" in plain
        assert "--transport" in plain

    def test_toolkit_invalid_transport(self):
        from initrunner.cli.main import app

        result = runner.invoke(app, ["mcp", "toolkit", "--transport", "grpc"])
        assert result.exit_code == 1

    def test_toolkit_missing_config_file(self):
        from initrunner.cli.main import app

        result = runner.invoke(app, ["mcp", "toolkit", "--config", "/nonexistent/toolkit.yaml"])
        assert result.exit_code == 1

    def test_toolkit_unknown_tool(self):
        from initrunner.cli.main import app

        result = runner.invoke(app, ["mcp", "toolkit", "--tools", "nonexistent_tool"])
        assert result.exit_code == 1

    @patch("initrunner.mcp.gateway.run_mcp_gateway")
    def test_toolkit_wiring_defaults(self, mock_run):
        from initrunner.cli.main import app

        result = runner.invoke(app, ["mcp", "toolkit"])
        assert result.exit_code == 0
        mock_run.assert_called_once()
        call_kwargs = mock_run.call_args
        assert call_kwargs[1]["transport"] == "stdio"

    @patch("initrunner.mcp.gateway.run_mcp_gateway")
    def test_toolkit_wiring_with_tools(self, mock_run):
        from initrunner.cli.main import app

        result = runner.invoke(app, ["mcp", "toolkit", "--tools", "search,datetime"])
        assert result.exit_code == 0
        mock_run.assert_called_once()

    @patch("initrunner.mcp.gateway.run_mcp_gateway")
    def test_toolkit_wiring_with_config(self, mock_run, tmp_path):
        from initrunner.cli.main import app

        config_file = tmp_path / "toolkit.yaml"
        config_file.write_text(
            textwrap.dedent("""\
            server_name: test-toolkit
            tools:
              datetime:
                default_timezone: UTC
            """)
        )
        result = runner.invoke(app, ["mcp", "toolkit", "--config", str(config_file)])
        assert result.exit_code == 0
        mock_run.assert_called_once()

    @patch("initrunner.mcp.gateway.run_mcp_gateway")
    def test_toolkit_server_name_override(self, mock_run):
        from initrunner.cli.main import app

        result = runner.invoke(app, ["mcp", "toolkit", "--server-name", "my-server"])
        assert result.exit_code == 0
        mock_run.assert_called_once()
        # Verify the FastMCP instance was built with the custom name
        mcp_instance = mock_run.call_args[0][0]
        assert mcp_instance.name == "my-server"

    @patch("initrunner.mcp.gateway.run_mcp_gateway")
    def test_toolkit_transport_sse(self, mock_run):
        from initrunner.cli.main import app

        result = runner.invoke(app, ["mcp", "toolkit", "--transport", "sse", "--port", "9090"])
        assert result.exit_code == 0
        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["transport"] == "sse"
        assert call_kwargs["port"] == 9090


# ---------------------------------------------------------------------------
# TestBuildToolkitSync (services layer)
# ---------------------------------------------------------------------------


class TestBuildToolkitSync:
    def test_build_without_config(self):
        from initrunner.services.operations import build_toolkit_sync

        mcp = build_toolkit_sync()
        assert mcp is not None

    def test_build_with_tool_names(self):
        from initrunner.services.operations import build_toolkit_sync

        mcp = build_toolkit_sync(tool_names=["datetime"])
        assert mcp is not None

    def test_build_with_server_name(self):
        from initrunner.services.operations import build_toolkit_sync

        mcp = build_toolkit_sync(server_name="custom-name")
        assert mcp.name == "custom-name"  # type: ignore[union-attr]

    def test_build_with_config_path(self, tmp_path):
        from initrunner.services.operations import build_toolkit_sync

        config_file = tmp_path / "toolkit.yaml"
        config_file.write_text(
            textwrap.dedent("""\
            server_name: from-file
            tools:
              datetime: {}
            """)
        )
        mcp = build_toolkit_sync(config_path=config_file)
        assert mcp.name == "from-file"  # type: ignore[union-attr]
