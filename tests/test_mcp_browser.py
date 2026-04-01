"""Tests for the browser MCP server (initrunner.mcp.browser)."""

from __future__ import annotations

import asyncio
import re
from unittest.mock import patch

from typer.testing import CliRunner

from initrunner.mcp.browser import BrowserMCPConfig, _check_url, _run_ab, build_browser_mcp

runner = CliRunner()


def _get_tool_fn(mcp, name):  # type: ignore[no-untyped-def]
    """Extract a tool function from a FastMCP instance by name."""
    tool = asyncio.run(mcp.get_tool(name))
    return tool.fn


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


class TestBrowserMCPConfig:
    def test_defaults(self):
        cfg = BrowserMCPConfig()
        assert cfg.server_name == "initrunner-browser"
        assert cfg.headless is True
        assert cfg.timeout_seconds == 30
        assert cfg.allowed_domains == []
        assert cfg.blocked_domains == []
        assert cfg.max_output_bytes == 512_000
        assert cfg.screenshot_dir == ""
        assert cfg.session_name == ""
        assert cfg.agent_browser_path == "agent-browser"

    def test_custom_values(self):
        cfg = BrowserMCPConfig(
            session_name="test-session",
            allowed_domains=["example.com"],
            headless=False,
            timeout_seconds=60,
        )
        assert cfg.session_name == "test-session"
        assert cfg.allowed_domains == ["example.com"]
        assert cfg.headless is False
        assert cfg.timeout_seconds == 60


# ---------------------------------------------------------------------------
# MCP registration
# ---------------------------------------------------------------------------


class TestBuildBrowserMCP:
    def test_returns_fastmcp_with_expected_tools(self):
        mcp = build_browser_mcp()
        tools = asyncio.run(mcp.list_tools())
        tool_names = {t.name for t in tools}
        expected = {
            "open_url",
            "snapshot",
            "click",
            "fill",
            "select",
            "press",
            "wait_for",
            "get_text",
            "get_url",
            "get_title",
            "screenshot",
            "close_browser",
        }
        assert expected == tool_names

    def test_default_config_used(self):
        mcp = build_browser_mcp()
        assert mcp.name == "initrunner-browser"

    def test_custom_server_name(self):
        cfg = BrowserMCPConfig(server_name="my-browser")
        mcp = build_browser_mcp(cfg)
        assert mcp.name == "my-browser"


# ---------------------------------------------------------------------------
# Subprocess helper
# ---------------------------------------------------------------------------


class TestRunAb:
    def test_happy_path(self):
        cfg = BrowserMCPConfig()
        with (
            patch("initrunner.mcp.browser.run_subprocess_text") as mock_run,
            patch("shutil.which", return_value="/usr/bin/agent-browser"),
        ):
            mock_run.return_value = ("Page loaded\n", "", 0)
            result = _run_ab(["open", "https://example.com"], cfg)
            assert "Page loaded" in result
            mock_run.assert_called_once()
            cmd = mock_run.call_args[0][0]
            assert cmd[0] == "agent-browser"
            assert "open" in cmd
            assert "https://example.com" in cmd

    def test_session_name_injected(self):
        cfg = BrowserMCPConfig(session_name="my-session")
        with (
            patch("initrunner.mcp.browser.run_subprocess_text") as mock_run,
            patch("shutil.which", return_value="/usr/bin/agent-browser"),
        ):
            mock_run.return_value = ("ok", "", 0)
            _run_ab(["open", "https://example.com"], cfg)
            cmd = mock_run.call_args[0][0]
            assert "--session-name" in cmd
            assert "my-session" in cmd

    def test_headed_mode(self):
        cfg = BrowserMCPConfig(headless=False)
        with (
            patch("initrunner.mcp.browser.run_subprocess_text") as mock_run,
            patch("shutil.which", return_value="/usr/bin/agent-browser"),
        ):
            mock_run.return_value = ("ok", "", 0)
            _run_ab(["open", "https://example.com"], cfg)
            cmd = mock_run.call_args[0][0]
            assert "--headed" in cmd

    def test_missing_binary(self):
        cfg = BrowserMCPConfig()
        with patch("shutil.which", return_value=None):
            result = _run_ab(["open", "https://example.com"], cfg)
            assert "Error:" in result
            assert "not found" in result
            assert "npm i -g agent-browser" in result

    def test_timeout(self):
        from initrunner.agent._subprocess import SubprocessTimeout

        cfg = BrowserMCPConfig(timeout_seconds=5)
        with (
            patch("initrunner.mcp.browser.run_subprocess_text") as mock_run,
            patch("shutil.which", return_value="/usr/bin/agent-browser"),
        ):
            mock_run.side_effect = SubprocessTimeout(5)
            result = _run_ab(["open", "https://example.com"], cfg)
            assert "Error:" in result
            assert "timed out" in result

    def test_nonzero_exit(self):
        cfg = BrowserMCPConfig()
        with (
            patch("initrunner.mcp.browser.run_subprocess_text") as mock_run,
            patch("shutil.which", return_value="/usr/bin/agent-browser"),
        ):
            mock_run.return_value = ("", "Navigation failed", 1)
            result = _run_ab(["open", "https://example.com"], cfg)
            assert "Error:" in result
            assert "Navigation failed" in result

    def test_output_truncation(self):
        cfg = BrowserMCPConfig(max_output_bytes=20)
        with (
            patch("initrunner.mcp.browser.run_subprocess_text") as mock_run,
            patch("shutil.which", return_value="/usr/bin/agent-browser"),
        ):
            mock_run.return_value = ("x" * 100, "", 0)
            result = _run_ab(["snapshot", "-i"], cfg)
            assert len(result) <= 20


# ---------------------------------------------------------------------------
# URL security
# ---------------------------------------------------------------------------


class TestCheckUrl:
    def test_file_url_blocked(self):
        cfg = BrowserMCPConfig()
        result = _check_url("file:///etc/passwd", cfg)
        assert result is not None
        assert "file://" in result

    def test_http_allowed(self):
        cfg = BrowserMCPConfig()
        with patch("initrunner.mcp.browser.validate_url_ssrf", return_value=None):
            result = _check_url("https://example.com", cfg)
            assert result is None

    def test_ssrf_blocked(self):
        cfg = BrowserMCPConfig()
        with patch(
            "initrunner.mcp.browser.validate_url_ssrf",
            return_value="Error: SSRF blocked",
        ):
            result = _check_url("http://169.254.169.254/metadata", cfg)
            assert result is not None
            assert "SSRF" in result

    def test_domain_allowlist(self):
        cfg = BrowserMCPConfig(allowed_domains=["example.com"])
        with patch("initrunner.mcp.browser.validate_url_ssrf", return_value=None):
            result = _check_url("https://evil.com", cfg)
            assert result is not None
            assert "not in the allowed domains" in result

    def test_domain_blocklist(self):
        cfg = BrowserMCPConfig(blocked_domains=["evil.com"])
        with patch("initrunner.mcp.browser.validate_url_ssrf", return_value=None):
            result = _check_url("https://evil.com", cfg)
            assert result is not None
            assert "blocked" in result

    def test_unsupported_scheme(self):
        cfg = BrowserMCPConfig()
        result = _check_url("ftp://example.com/file", cfg)
        assert result is not None
        assert "unsupported" in result


# ---------------------------------------------------------------------------
# Tool behavior (mocked subprocess)
# ---------------------------------------------------------------------------


def _mock_run_ab(return_value: str = "ok"):
    """Patch _run_ab to return a fixed value."""
    return patch("initrunner.mcp.browser._run_ab", return_value=return_value)


class TestOpenUrl:
    def test_returns_title_and_url(self):
        mcp = build_browser_mcp()
        fn = _get_tool_fn(mcp, "open_url")
        side_effects = ["ok", "ok", "Example Page", "https://example.com"]
        with (
            patch("initrunner.mcp.browser._run_ab", side_effect=side_effects),
            patch("initrunner.mcp.browser._check_url", return_value=None),
        ):
            result = fn(url="https://example.com")
            assert "Example Page" in result
            assert "https://example.com" in result

    def test_no_snapshot_in_output(self):
        mcp = build_browser_mcp()
        fn = _get_tool_fn(mcp, "open_url")
        side_effects = ["opened", "waited", "My Title", "https://test.com"]
        with (
            patch("initrunner.mcp.browser._run_ab", side_effect=side_effects),
            patch("initrunner.mcp.browser._check_url", return_value=None),
        ):
            result = fn(url="https://test.com")
            assert "Navigated to:" in result
            assert "@e" not in result

    def test_invalid_wait_until(self):
        mcp = build_browser_mcp()
        fn = _get_tool_fn(mcp, "open_url")
        result = fn(url="https://example.com", wait_until="invalid")
        assert "Error:" in result

    def test_url_check_fails(self):
        mcp = build_browser_mcp()
        fn = _get_tool_fn(mcp, "open_url")
        with patch("initrunner.mcp.browser._check_url", return_value="Error: blocked"):
            result = fn(url="http://evil.com")
            assert result == "Error: blocked"

    def test_wait_until_none_skips_wait(self):
        mcp = build_browser_mcp()
        fn = _get_tool_fn(mcp, "open_url")
        calls = []

        def mock_run(args, cfg):
            calls.append(args)
            if args[0] == "get" and args[1] == "title":
                return "Title"
            if args[0] == "get" and args[1] == "url":
                return "https://example.com"
            return "ok"

        with (
            patch("initrunner.mcp.browser._run_ab", side_effect=mock_run),
            patch("initrunner.mcp.browser._check_url", return_value=None),
        ):
            fn(url="https://example.com", wait_until="none")
            assert not any(c[0] == "wait" for c in calls)


class TestSnapshot:
    def test_interactive_only(self):
        mcp = build_browser_mcp()
        fn = _get_tool_fn(mcp, "snapshot")
        with _mock_run_ab("@e1 button Submit\n@e2 input email") as mock:
            result = fn()
            assert "@e1" in result
            args = mock.call_args[0][0]
            assert "-i" in args

    def test_with_selector(self):
        mcp = build_browser_mcp()
        fn = _get_tool_fn(mcp, "snapshot")
        with _mock_run_ab("@e1 button") as mock:
            fn(selector="#main-form")
            args = mock.call_args[0][0]
            assert "-s" in args
            assert "#main-form" in args


class TestClick:
    def test_basic_click(self):
        mcp = build_browser_mcp()
        fn = _get_tool_fn(mcp, "click")
        with _mock_run_ab("clicked") as mock:
            result = fn(ref="@e1")
            assert "clicked" in result
            args = mock.call_args[0][0]
            assert "click" in args
            assert "@e1" in args

    def test_click_with_wait(self):
        mcp = build_browser_mcp()
        fn = _get_tool_fn(mcp, "click")
        call_count = [0]

        def mock_run(args, cfg):
            call_count[0] += 1
            return "ok"

        with patch("initrunner.mcp.browser._run_ab", side_effect=mock_run):
            fn(ref="@e1", wait_until="networkidle")
            assert call_count[0] == 2


class TestFillSelectPress:
    def test_fill(self):
        mcp = build_browser_mcp()
        fn = _get_tool_fn(mcp, "fill")
        with _mock_run_ab("filled") as mock:
            fn(ref="@e1", value="hello@test.com")
            args = mock.call_args[0][0]
            assert "fill" in args
            assert "@e1" in args
            assert "hello@test.com" in args

    def test_select(self):
        mcp = build_browser_mcp()
        fn = _get_tool_fn(mcp, "select")
        with _mock_run_ab("selected") as mock:
            fn(ref="@e1", value="Option A")
            args = mock.call_args[0][0]
            assert "select" in args

    def test_press(self):
        mcp = build_browser_mcp()
        fn = _get_tool_fn(mcp, "press")
        with _mock_run_ab("pressed") as mock:
            fn(key="Enter")
            args = mock.call_args[0][0]
            assert "press" in args
            assert "Enter" in args


class TestWaitFor:
    def test_wait_for_ref(self):
        mcp = build_browser_mcp()
        fn = _get_tool_fn(mcp, "wait_for")
        with _mock_run_ab("found") as mock:
            fn(ref="@e1")
            args = mock.call_args[0][0]
            assert "wait" in args
            assert "@e1" in args

    def test_wait_for_text(self):
        mcp = build_browser_mcp()
        fn = _get_tool_fn(mcp, "wait_for")
        with _mock_run_ab("found") as mock:
            fn(text="Loading complete")
            args = mock.call_args[0][0]
            assert "--text" in args

    def test_wait_for_url(self):
        mcp = build_browser_mcp()
        fn = _get_tool_fn(mcp, "wait_for")
        with _mock_run_ab("matched") as mock:
            fn(url_pattern="**/dashboard")
            args = mock.call_args[0][0]
            assert "--url" in args

    def test_wait_for_load(self):
        mcp = build_browser_mcp()
        fn = _get_tool_fn(mcp, "wait_for")
        with _mock_run_ab("loaded") as mock:
            fn(load="networkidle")
            args = mock.call_args[0][0]
            assert "--load" in args

    def test_wait_for_milliseconds(self):
        mcp = build_browser_mcp()
        fn = _get_tool_fn(mcp, "wait_for")
        with _mock_run_ab("waited") as mock:
            fn(milliseconds=2000)
            args = mock.call_args[0][0]
            assert "2000" in args

    def test_zero_modes_error(self):
        mcp = build_browser_mcp()
        fn = _get_tool_fn(mcp, "wait_for")
        result = fn()
        assert "Error:" in result
        assert "exactly one mode" in result

    def test_multiple_modes_error(self):
        mcp = build_browser_mcp()
        fn = _get_tool_fn(mcp, "wait_for")
        result = fn(ref="@e1", text="hello")
        assert "Error:" in result
        assert "exactly one mode" in result

    def test_custom_state(self):
        mcp = build_browser_mcp()
        fn = _get_tool_fn(mcp, "wait_for")
        with _mock_run_ab("ok") as mock:
            fn(ref="@e1", state="hidden")
            args = mock.call_args[0][0]
            assert "--state" in args
            assert "hidden" in args


class TestGetters:
    def test_get_text_with_ref(self):
        mcp = build_browser_mcp()
        fn = _get_tool_fn(mcp, "get_text")
        with _mock_run_ab("Hello World") as mock:
            result = fn(ref="@e1")
            assert "Hello World" in result
            args = mock.call_args[0][0]
            assert "@e1" in args

    def test_get_text_full_page(self):
        mcp = build_browser_mcp()
        fn = _get_tool_fn(mcp, "get_text")
        with _mock_run_ab("Full page text") as mock:
            fn()
            args = mock.call_args[0][0]
            assert args == ["get", "text"]

    def test_get_url(self):
        mcp = build_browser_mcp()
        fn = _get_tool_fn(mcp, "get_url")
        with _mock_run_ab("https://example.com"):
            result = fn()
            assert "https://example.com" in result

    def test_get_title(self):
        mcp = build_browser_mcp()
        fn = _get_tool_fn(mcp, "get_title")
        with _mock_run_ab("My Page Title"):
            result = fn()
            assert "My Page Title" in result


class TestScreenshot:
    def test_basic_screenshot(self, tmp_path):
        cfg = BrowserMCPConfig(screenshot_dir=str(tmp_path))
        mcp = build_browser_mcp(cfg)
        fn = _get_tool_fn(mcp, "screenshot")
        dest = tmp_path / "screenshot.png"

        def mock_run(args, cfg):
            dest.write_bytes(b"\x89PNG fake")
            return "Screenshot saved"

        with patch("initrunner.mcp.browser._run_ab", side_effect=mock_run):
            result = fn()
            assert str(tmp_path) in result

    def test_full_page_flag(self):
        mcp = build_browser_mcp()
        fn = _get_tool_fn(mcp, "screenshot")
        with patch("initrunner.mcp.browser._run_ab", return_value="ok") as mock:
            fn(full_page=True)
            args = mock.call_args[0][0]
            assert "--full" in args

    def test_annotate_flag(self):
        mcp = build_browser_mcp()
        fn = _get_tool_fn(mcp, "screenshot")
        with patch("initrunner.mcp.browser._run_ab", return_value="ok") as mock:
            fn(annotate=True)
            args = mock.call_args[0][0]
            assert "--annotate" in args


class TestCloseBrowser:
    def test_close(self):
        mcp = build_browser_mcp()
        fn = _get_tool_fn(mcp, "close_browser")
        with _mock_run_ab("closed") as mock:
            result = fn()
            assert "closed" in result
            args = mock.call_args[0][0]
            assert "close" in args


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


class TestBrowserCLI:
    def test_help(self):
        from initrunner.cli.main import app

        result = runner.invoke(app, ["mcp", "browser", "--help"])
        assert result.exit_code == 0
        plain = re.sub(r"\x1b\[[0-9;]*m", "", result.output)
        assert "browser" in plain.lower()
        assert "--transport" in plain
        assert "--session-name" in plain
        assert "--allowed-domains" in plain

    def test_invalid_transport(self):
        from initrunner.cli.main import app

        result = runner.invoke(app, ["mcp", "browser", "--transport", "grpc"])
        assert result.exit_code == 1
