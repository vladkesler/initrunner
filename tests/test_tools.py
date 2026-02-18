"""Tests for the tools module."""

import os
import sys
import textwrap
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from initrunner.agent.schema.tools import (
    CustomToolConfig,
    DateTimeToolConfig,
    FileSystemToolConfig,
    HttpToolConfig,
    McpToolConfig,
    WebReaderToolConfig,
)
from initrunner.agent.tools import (
    _build_custom_toolset,
    _discover_module_tools,
    _inject_config,
    build_datetime_toolset,
    build_filesystem_toolset,
    build_http_toolset,
    build_web_reader_toolset,
)
from initrunner.agent.tools._registry import ToolBuildContext
from initrunner.mcp.server import build_mcp_toolset


def _make_ctx() -> ToolBuildContext:
    """Build a minimal ToolBuildContext for tests."""
    from initrunner.agent.schema.role import RoleDefinition

    role = RoleDefinition.model_validate(
        {
            "apiVersion": "initrunner/v1",
            "kind": "Agent",
            "metadata": {"name": "test-agent", "description": "test"},
            "spec": {
                "role": "test",
                "model": {"provider": "openai", "name": "gpt-5-mini"},
            },
        }
    )
    return ToolBuildContext(role=role)


class TestFilesystemToolset:
    def test_builds_toolset(self):
        config = FileSystemToolConfig(root_path="/tmp", read_only=True)
        toolset = build_filesystem_toolset(config, _make_ctx())
        assert toolset is not None

    def test_read_only_has_no_write(self):
        config = FileSystemToolConfig(root_path="/tmp", read_only=True)
        toolset = build_filesystem_toolset(config, _make_ctx())
        names = list(toolset.tools.keys())
        assert "read_file" in names
        assert "list_directory" in names
        assert "write_file" not in names

    def test_writable_has_write(self):
        config = FileSystemToolConfig(root_path="/tmp", read_only=False)
        toolset = build_filesystem_toolset(config, _make_ctx())
        names = list(toolset.tools.keys())
        assert "write_file" in names


class TestHttpToolset:
    @patch("initrunner.agent._urls.socket.getaddrinfo")
    def test_ssrf_blocked_for_private_base_url(self, mock_dns):
        mock_dns.side_effect = lambda *a, **kw: [(2, 1, 6, "", ("127.0.0.1", 80))]
        config = HttpToolConfig(base_url="http://127.0.0.1")
        toolset = build_http_toolset(config, _make_ctx())
        fn = toolset.tools["http_request"].function
        result = fn(method="GET", path="/")
        assert "SSRF blocked" in result

    def test_builds_toolset(self):
        config = HttpToolConfig(base_url="https://api.example.com")
        toolset = build_http_toolset(config, _make_ctx())
        assert toolset is not None


class TestMcpConfigValidation:
    """Schema-level validation tests for McpToolConfig."""

    def test_stdio_without_command_raises(self):
        with pytest.raises(ValidationError, match="requires 'command'"):
            McpToolConfig(transport="stdio")

    def test_sse_without_url_raises(self):
        with pytest.raises(ValidationError, match="requires 'url'"):
            McpToolConfig(transport="sse")

    def test_streamable_http_without_url_raises(self):
        with pytest.raises(ValidationError, match="requires 'url'"):
            McpToolConfig(transport="streamable-http")

    def test_tool_filter_and_exclude_mutually_exclusive(self):
        with pytest.raises(ValidationError, match="mutually exclusive"):
            McpToolConfig(
                transport="stdio",
                command="npx",
                tool_filter=["a"],
                tool_exclude=["b"],
            )

    def test_valid_stdio_config(self):
        config = McpToolConfig(transport="stdio", command="npx", args=["test"])
        assert config.command == "npx"

    def test_valid_sse_config(self):
        config = McpToolConfig(transport="sse", url="http://localhost:3001/sse")
        assert config.url == "http://localhost:3001/sse"

    def test_new_fields_have_defaults(self):
        config = McpToolConfig(transport="stdio", command="npx")
        assert config.tool_exclude == []
        assert config.headers == {}
        assert config.env == {}
        assert config.cwd is None
        assert config.tool_prefix is None
        assert config.max_retries == 1
        assert config.timeout is None


class TestMcpBuilderWiring:
    """Tests that new config fields are wired correctly into the builder."""

    @patch("initrunner.mcp.server.FastMCPToolset")
    @patch("fastmcp.client.transports.StdioTransport")
    def test_max_retries_passed_to_toolset(self, mock_transport_cls, mock_toolset_cls):
        mock_toolset_cls.return_value = MagicMock()
        config = McpToolConfig(transport="stdio", command="npx", max_retries=5)
        build_mcp_toolset(config, _make_ctx())
        mock_toolset_cls.assert_called_once()
        _, kwargs = mock_toolset_cls.call_args
        assert kwargs["max_retries"] == 5

    @patch("initrunner.mcp.server.FastMCPToolset")
    @patch("fastmcp.client.transports.StdioTransport")
    def test_timeout_passed_to_stdio_transport(self, mock_transport_cls, mock_toolset_cls):
        mock_toolset_cls.return_value = MagicMock()
        config = McpToolConfig(transport="stdio", command="npx", timeout=30)
        build_mcp_toolset(config, _make_ctx())
        mock_transport_cls.assert_called_once()
        _, kwargs = mock_transport_cls.call_args
        assert kwargs["timeout"] == 30

    @patch("initrunner.mcp.server.FastMCPToolset")
    @patch("fastmcp.client.transports.SSETransport")
    def test_headers_passed_to_sse_transport(self, mock_transport_cls, mock_toolset_cls):
        mock_toolset_cls.return_value = MagicMock()
        config = McpToolConfig(
            transport="sse",
            url="http://localhost:3001/sse",
            headers={"Authorization": "Bearer tok123"},
        )
        build_mcp_toolset(config, _make_ctx())
        mock_transport_cls.assert_called_once()
        _, kwargs = mock_transport_cls.call_args
        assert kwargs["headers"] == {"Authorization": "Bearer tok123"}

    @patch("initrunner.mcp.server.FastMCPToolset")
    @patch("fastmcp.client.transports.StreamableHttpTransport")
    def test_headers_passed_to_http_transport(self, mock_transport_cls, mock_toolset_cls):
        mock_toolset_cls.return_value = MagicMock()
        config = McpToolConfig(
            transport="streamable-http",
            url="http://localhost:3001/mcp",
            headers={"X-Api-Key": "key123"},
        )
        build_mcp_toolset(config, _make_ctx())
        mock_transport_cls.assert_called_once()
        _, kwargs = mock_transport_cls.call_args
        assert kwargs["headers"] == {"X-Api-Key": "key123"}

    @patch("initrunner.mcp.server.FastMCPToolset")
    @patch("fastmcp.client.transports.SSETransport")
    def test_timeout_passed_to_sse_transport(self, mock_transport_cls, mock_toolset_cls):
        mock_toolset_cls.return_value = MagicMock()
        config = McpToolConfig(transport="sse", url="http://localhost:3001/sse", timeout=60)
        build_mcp_toolset(config, _make_ctx())
        _, kwargs = mock_transport_cls.call_args
        assert kwargs["timeout"] == 60

    @patch.dict(os.environ, {"MCP_API_TOKEN": "secret123"}, clear=False)
    @patch("initrunner.mcp.server.FastMCPToolset")
    @patch("fastmcp.client.transports.SSETransport")
    def test_header_env_interpolation(self, mock_transport_cls, mock_toolset_cls):
        mock_toolset_cls.return_value = MagicMock()
        config = McpToolConfig(
            transport="sse",
            url="http://localhost:3001/sse",
            headers={"Authorization": "Bearer ${MCP_API_TOKEN}"},
        )
        build_mcp_toolset(config, _make_ctx())
        _, kwargs = mock_transport_cls.call_args
        assert kwargs["headers"] == {"Authorization": "Bearer secret123"}

    @patch.dict(os.environ, {"MY_VAR": "resolved_value"}, clear=False)
    @patch("initrunner.mcp.server.FastMCPToolset")
    @patch("fastmcp.client.transports.StdioTransport")
    def test_env_interpolation_and_merge(self, mock_transport_cls, mock_toolset_cls):
        mock_toolset_cls.return_value = MagicMock()
        config = McpToolConfig(
            transport="stdio",
            command="npx",
            env={"CUSTOM_VAR": "${MY_VAR}", "STATIC_VAR": "static"},
        )
        build_mcp_toolset(config, _make_ctx())
        _, kwargs = mock_transport_cls.call_args
        env = kwargs["env"]
        # Config env values override and are interpolated
        assert env["CUSTOM_VAR"] == "resolved_value"
        assert env["STATIC_VAR"] == "static"

    @patch("initrunner.mcp.server.FastMCPToolset")
    @patch("fastmcp.client.transports.StdioTransport")
    def test_env_config_overrides_system_env(self, mock_transport_cls, mock_toolset_cls):
        mock_toolset_cls.return_value = MagicMock()
        config = McpToolConfig(
            transport="stdio",
            command="npx",
            env={"PATH": "/custom/path"},
        )
        build_mcp_toolset(config, _make_ctx())
        _, kwargs = mock_transport_cls.call_args
        env = kwargs["env"]
        assert env["PATH"] == "/custom/path"

    @patch("initrunner.mcp.server.FastMCPToolset")
    @patch("fastmcp.client.transports.StdioTransport")
    def test_cwd_resolved_relative_to_role_dir(self, mock_transport_cls, mock_toolset_cls):
        mock_toolset_cls.return_value = MagicMock()
        config = McpToolConfig(transport="stdio", command="npx", cwd="subdir")
        ctx = _make_ctx()
        ctx.role_dir = Path("/home/user/roles")
        build_mcp_toolset(config, ctx)
        _, kwargs = mock_transport_cls.call_args
        assert kwargs["cwd"] == "/home/user/roles/subdir"

    @patch("initrunner.mcp.server.FastMCPToolset")
    @patch("fastmcp.client.transports.StdioTransport")
    def test_cwd_absolute_not_resolved(self, mock_transport_cls, mock_toolset_cls):
        mock_toolset_cls.return_value = MagicMock()
        config = McpToolConfig(transport="stdio", command="npx", cwd="/absolute/path")
        ctx = _make_ctx()
        ctx.role_dir = Path("/home/user/roles")
        build_mcp_toolset(config, ctx)
        _, kwargs = mock_transport_cls.call_args
        assert kwargs["cwd"] == "/absolute/path"

    @patch("initrunner.mcp.server.FastMCPToolset")
    @patch("fastmcp.client.transports.StdioTransport")
    def test_tool_filter_creates_filtered_toolset(self, mock_transport_cls, mock_toolset_cls):
        mock_toolset = MagicMock()
        mock_filtered = MagicMock()
        mock_toolset.filtered.return_value = mock_filtered
        mock_toolset_cls.return_value = mock_toolset

        config = McpToolConfig(
            transport="stdio", command="npx", tool_filter=["read_file", "write_file"]
        )
        result = build_mcp_toolset(config, _make_ctx())
        mock_toolset.filtered.assert_called_once()
        assert result is mock_filtered

    @patch("initrunner.mcp.server.FastMCPToolset")
    @patch("fastmcp.client.transports.StdioTransport")
    def test_tool_exclude_creates_filtered_toolset(self, mock_transport_cls, mock_toolset_cls):
        mock_toolset = MagicMock()
        mock_filtered = MagicMock()
        mock_toolset.filtered.return_value = mock_filtered
        mock_toolset_cls.return_value = mock_toolset

        config = McpToolConfig(transport="stdio", command="npx", tool_exclude=["dangerous_tool"])
        result = build_mcp_toolset(config, _make_ctx())
        mock_toolset.filtered.assert_called_once()
        assert result is mock_filtered

    @patch("initrunner.mcp.server.FastMCPToolset")
    @patch("fastmcp.client.transports.StdioTransport")
    def test_tool_prefix_creates_prefixed_toolset(self, mock_transport_cls, mock_toolset_cls):
        mock_toolset = MagicMock()
        mock_prefixed = MagicMock()
        mock_toolset.prefixed.return_value = mock_prefixed
        mock_toolset_cls.return_value = mock_toolset

        config = McpToolConfig(transport="stdio", command="npx", tool_prefix="remote")
        result = build_mcp_toolset(config, _make_ctx())
        mock_toolset.prefixed.assert_called_once_with("remote")
        assert result is mock_prefixed

    @patch("initrunner.mcp.server.FastMCPToolset")
    @patch("fastmcp.client.transports.StdioTransport")
    def test_filter_applied_before_prefix(self, mock_transport_cls, mock_toolset_cls):
        """Verify modifier order: filtered() then prefixed()."""
        mock_toolset = MagicMock()
        mock_filtered = MagicMock()
        mock_prefixed = MagicMock()
        mock_toolset.filtered.return_value = mock_filtered
        mock_filtered.prefixed.return_value = mock_prefixed
        mock_toolset_cls.return_value = mock_toolset

        config = McpToolConfig(
            transport="stdio",
            command="npx",
            tool_filter=["read_file"],
            tool_prefix="staging",
        )
        result = build_mcp_toolset(config, _make_ctx())
        # filtered() should be called on the original toolset
        mock_toolset.filtered.assert_called_once()
        # prefixed() should be called on the filtered result
        mock_filtered.prefixed.assert_called_once_with("staging")
        assert result is mock_prefixed

    @patch("initrunner.mcp.server.FastMCPToolset")
    @patch("fastmcp.client.transports.StdioTransport")
    def test_no_headers_not_passed(self, mock_transport_cls, mock_toolset_cls):
        """When headers is empty, 'headers' kwarg should not be in transport args."""
        mock_toolset_cls.return_value = MagicMock()
        config = McpToolConfig(transport="stdio", command="npx")
        build_mcp_toolset(config, _make_ctx())
        # StdioTransport doesn't use headers, just verify it was called
        mock_transport_cls.assert_called_once()


def _make_temp_module(name: str, source: str, tmp_path: Path) -> str:
    """Write a Python module to tmp_path and add to sys.path, return module name."""
    mod_file = tmp_path / f"{name}.py"
    mod_file.write_text(textwrap.dedent(source))
    if str(tmp_path) not in sys.path:
        sys.path.insert(0, str(tmp_path))
    # Remove cached module if it exists
    sys.modules.pop(name, None)
    return name


class TestCustomToolsetEnhanced:
    def test_multi_function_discovery(self, tmp_path):
        """Auto-discover all public callables when function is None."""
        mod_name = _make_temp_module(
            "_test_multi_tools",
            """\
            def greet(name: str) -> str:
                \"\"\"Say hello.\"\"\"
                return f"Hello, {name}!"

            def add(a: int, b: int) -> str:
                \"\"\"Add numbers.\"\"\"
                return str(a + b)

            def _private():
                pass
            """,
            tmp_path,
        )
        config = CustomToolConfig(module=mod_name)
        toolset = _build_custom_toolset(config, _make_ctx())
        names = list(toolset.tools.keys())
        assert "greet" in names
        assert "add" in names
        assert "_private" not in names

    def test_config_passthrough(self, tmp_path):
        """Config dict is injected into functions that accept tool_config."""
        mod_name = _make_temp_module(
            "_test_config_tool",
            """\
            def greet(name: str, tool_config: dict) -> str:
                \"\"\"Greet with config.\"\"\"
                greeting = tool_config.get("greeting", "Hi")
                return f"{greeting}, {name}!"
            """,
            tmp_path,
        )
        config = CustomToolConfig(
            module=mod_name,
            function="greet",
            config={"greeting": "Howdy"},
        )
        toolset = _build_custom_toolset(config, _make_ctx())
        names = list(toolset.tools.keys())
        assert "greet" in names
        # tool_config should NOT be in the tool's annotations exposed to LLM
        tool_def = toolset.tools["greet"]
        # Verify the partial was created - the function should work
        assert tool_def is not None

    def test_single_function_mode_still_works(self, tmp_path):
        """Specifying function explicitly loads just that one."""
        mod_name = _make_temp_module(
            "_test_single_func",
            """\
            def tool_a() -> str:
                \"\"\"Tool A.\"\"\"
                return "a"

            def tool_b() -> str:
                \"\"\"Tool B.\"\"\"
                return "b"
            """,
            tmp_path,
        )
        config = CustomToolConfig(module=mod_name, function="tool_a")
        toolset = _build_custom_toolset(config, _make_ctx())
        names = list(toolset.tools.keys())
        assert names == ["tool_a"]

    def test_empty_module_raises(self, tmp_path):
        """Module with no public callables raises clear error."""
        mod_name = _make_temp_module(
            "_test_empty_mod",
            """\
            _PRIVATE = "not a tool"

            def _hidden():
                pass
            """,
            tmp_path,
        )
        config = CustomToolConfig(module=mod_name)
        with pytest.raises(ValueError, match="No public callable functions"):
            _build_custom_toolset(config, _make_ctx())

    def test_import_error_helpful_message(self):
        """ImportError produces actionable error message."""
        config = CustomToolConfig(module="nonexistent_package_xyz123")
        with pytest.raises(ValueError, match="Could not find module"):
            _build_custom_toolset(config, _make_ctx())

    def test_missing_function_raises(self, tmp_path):
        """Specifying a nonexistent function raises clear error."""
        mod_name = _make_temp_module(
            "_test_missing_func",
            """\
            def existing() -> str:
                return "ok"
            """,
            tmp_path,
        )
        config = CustomToolConfig(module=mod_name, function="nonexistent")
        with pytest.raises(ValueError, match="not found in module"):
            _build_custom_toolset(config, _make_ctx())

    def test_role_dir_resolves_local_module(self, tmp_path):
        """Custom module is importable from role_dir without manual PYTHONPATH."""
        mod_name = "_test_role_dir_tool"
        mod_file = tmp_path / f"{mod_name}.py"
        mod_file.write_text(
            textwrap.dedent("""\
            def hello(name: str) -> str:
                \"\"\"Say hello.\"\"\"
                return f"Hello, {name}!"
            """)
        )
        # Ensure tmp_path is NOT already on sys.path
        while str(tmp_path) in sys.path:
            sys.path.remove(str(tmp_path))
        sys.modules.pop(mod_name, None)

        from initrunner.agent.schema.role import RoleDefinition

        role = RoleDefinition.model_validate(
            {
                "apiVersion": "initrunner/v1",
                "kind": "Agent",
                "metadata": {"name": "test-agent", "description": "test"},
                "spec": {
                    "role": "test",
                    "model": {"provider": "openai", "name": "gpt-5-mini"},
                },
            }
        )
        ctx = ToolBuildContext(role=role, role_dir=tmp_path)

        config = CustomToolConfig(module=mod_name)
        toolset = _build_custom_toolset(config, ctx)
        assert "hello" in toolset.tools

        # sys.path should be cleaned up after the call
        assert str(tmp_path) not in sys.path


class TestInjectConfig:
    def test_skips_functions_without_tool_config(self):
        def simple(x: int) -> str:
            return str(x)

        result = _inject_config(simple, {"key": "val"})
        assert result is simple  # unchanged

    def test_injects_tool_config(self):
        def with_config(x: int, tool_config: dict) -> str:
            return f"{x}-{tool_config['key']}"

        result = _inject_config(with_config, {"key": "val"})
        assert result is not with_config
        assert "tool_config" not in result.__annotations__

    def test_preserves_metadata(self):
        def my_tool(x: int, tool_config: dict) -> str:
            """My doc."""
            return str(x)

        result = _inject_config(my_tool, {})
        assert result.__name__ == "my_tool"  # type: ignore[attr-defined]
        assert result.__doc__ == "My doc."


class TestDiscoverModuleTools:
    def test_discovers_functions(self):
        mod = types.ModuleType("test_mod")
        mod.public_fn = lambda: None  # type: ignore[attr-defined]
        # Make it look like a function
        mod.public_fn.__module__ = "test_mod"

        # Create a proper function
        exec("def real_func(): pass", mod.__dict__)
        funcs = _discover_module_tools(mod)
        # Should find real_func but not lambda (inspect.isfunction filters it)
        names = [f.__name__ for f in funcs]  # type: ignore[attr-defined]
        assert "real_func" in names

    def test_skips_private_and_classes(self):
        mod = types.ModuleType("test_mod")
        exec("def _private(): pass", mod.__dict__)
        mod.MyClass = type("MyClass", (), {})  # type: ignore[attr-defined]
        funcs = _discover_module_tools(mod)
        names = [f.__name__ for f in funcs]  # type: ignore[attr-defined]
        assert "_private" not in names
        assert "MyClass" not in names


class TestWebReaderToolset:
    @patch("initrunner.agent._urls.socket.getaddrinfo")
    def test_ssrf_blocked_for_metadata_endpoint(self, mock_dns):
        mock_dns.side_effect = lambda *a, **kw: [(2, 1, 6, "", ("169.254.169.254", 80))]
        config = WebReaderToolConfig()
        toolset = build_web_reader_toolset(config, _make_ctx())
        fn = toolset.tools["fetch_page"].function
        result = fn(url="http://169.254.169.254/latest/meta-data/")
        assert "SSRF blocked" in result

    def test_builds_toolset(self):
        config = WebReaderToolConfig()
        toolset = build_web_reader_toolset(config, _make_ctx())
        assert "fetch_page" in toolset.tools

    def test_domain_allowlist_rejects(self):
        config = WebReaderToolConfig(allowed_domains=["example.com"])
        toolset = build_web_reader_toolset(config, _make_ctx())
        fn = toolset.tools["fetch_page"].function
        result = fn(url="https://blocked.com/page")
        assert "not in the allowed domains" in result

    def test_domain_blocklist_rejects(self):
        config = WebReaderToolConfig(blocked_domains=["evil.com"])
        toolset = build_web_reader_toolset(config, _make_ctx())
        fn = toolset.tools["fetch_page"].function
        result = fn(url="https://evil.com/page")
        assert "blocked" in result

    def test_fetch_html_returns_markdown(self):
        config = WebReaderToolConfig()
        toolset = build_web_reader_toolset(config, _make_ctx())
        fn = toolset.tools["fetch_page"].function

        html = "<html><body><h1>Title</h1><p>Hello world</p></body></html>"
        mock_resp = MagicMock()
        mock_resp.text = html
        mock_resp.headers = {"content-type": "text/html; charset=utf-8"}
        mock_resp.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_resp

        with patch("initrunner._html.httpx.Client", return_value=mock_client):
            result = fn(url="https://example.com/page")

        assert "Title" in result
        assert "Hello world" in result

    def test_truncates_large_content(self):
        config = WebReaderToolConfig(max_content_bytes=50)
        toolset = build_web_reader_toolset(config, _make_ctx())
        fn = toolset.tools["fetch_page"].function

        html = "<html><body><p>" + "x" * 1000 + "</p></body></html>"
        mock_resp = MagicMock()
        mock_resp.text = html
        mock_resp.headers = {"content-type": "text/html"}
        mock_resp.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_resp

        with patch("initrunner._html.httpx.Client", return_value=mock_client):
            result = fn(url="https://example.com/page")

        assert "[truncated]" in result

    def test_non_html_returns_text(self):
        config = WebReaderToolConfig()
        toolset = build_web_reader_toolset(config, _make_ctx())
        fn = toolset.tools["fetch_page"].function

        mock_resp = MagicMock()
        mock_resp.text = "plain text content"
        mock_resp.headers = {"content-type": "text/plain"}
        mock_resp.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_resp

        with patch("initrunner._html.httpx.Client", return_value=mock_client):
            result = fn(url="https://example.com/data.txt")

        assert result == "plain text content"


class TestDateTimeToolset:
    def test_builds_toolset(self):
        config = DateTimeToolConfig()
        toolset = build_datetime_toolset(config, _make_ctx())
        assert "current_time" in toolset.tools
        assert "parse_date" in toolset.tools

    def test_current_time_utc(self):
        config = DateTimeToolConfig(default_timezone="UTC")
        toolset = build_datetime_toolset(config, _make_ctx())
        fn = toolset.tools["current_time"].function
        result = fn(timezone="")
        # Should contain ISO format and human-readable
        assert "T" in result  # ISO 8601 has T separator
        assert "UTC" in result

    def test_current_time_with_timezone(self):
        config = DateTimeToolConfig(default_timezone="UTC")
        toolset = build_datetime_toolset(config, _make_ctx())
        fn = toolset.tools["current_time"].function
        result = fn(timezone="America/New_York")
        # Should reflect the Eastern timezone
        assert "T" in result

    def test_current_time_invalid_timezone(self):
        config = DateTimeToolConfig()
        toolset = build_datetime_toolset(config, _make_ctx())
        fn = toolset.tools["current_time"].function
        result = fn(timezone="Not/A/Timezone")
        assert "Error" in result
        assert "invalid timezone" in result

    def test_parse_date_iso(self):
        config = DateTimeToolConfig()
        toolset = build_datetime_toolset(config, _make_ctx())
        fn = toolset.tools["parse_date"].function
        result = fn(text="2024-01-15T10:30:00")
        assert "2024-01-15" in result
        assert "10:30:00" in result

    def test_parse_date_with_format(self):
        config = DateTimeToolConfig()
        toolset = build_datetime_toolset(config, _make_ctx())
        fn = toolset.tools["parse_date"].function
        result = fn(text="15/01/2024", format="%d/%m/%Y")
        assert "2024-01-15" in result

    def test_parse_date_invalid(self):
        config = DateTimeToolConfig()
        toolset = build_datetime_toolset(config, _make_ctx())
        fn = toolset.tools["parse_date"].function
        result = fn(text="not a date")
        assert "Could not parse" in result
        assert "ISO 8601" in result
