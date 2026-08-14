"""Tests for the no-arg CLI entry menu (Chat / starter / create / dashboard)."""

from __future__ import annotations

import io
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from initrunner.cli.main import app

runner = CliRunner()


class _FakeTTY(io.BytesIO):
    """BytesIO that reports isatty() == True."""

    def isatty(self):
        return True


_PATCH_DASHBOARD_AVAILABLE = "initrunner._compat.is_dashboard_available"
_PATCH_DISPATCH = "initrunner.cli._first_run.dispatch_first_run_choice"


def _configured_patches(monkeypatch, tmp_path):
    """Set up env for a configured provider."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("INITRUNNER_HOME", str(tmp_path / "home"))
    from initrunner.config import get_home_dir

    get_home_dir.cache_clear()


class TestDefaultEntryMenu:
    def test_dashboard_available_four_options_dashboard_last(self, monkeypatch, tmp_path):
        _configured_patches(monkeypatch, tmp_path)
        with (
            patch(_PATCH_DASHBOARD_AVAILABLE, return_value=True),
            patch(_PATCH_DISPATCH, MagicMock()),
        ):
            result = runner.invoke(app, [], input=_FakeTTY(b"1\n"))
        assert result.exit_code == 0
        assert "Chat" in result.output
        assert "Try a starter" in result.output
        assert "Create an agent" in result.output
        assert "Dashboard" in result.output
        # Dashboard is last: its number is 4
        assert "4. Dashboard" in result.output or "4]. Dashboard" in result.output.replace("[", "")
        chat_pos = result.output.index("Chat")
        dash_pos = result.output.index("Dashboard")
        assert chat_pos < dash_pos

    def test_dashboard_unavailable_three_options(self, monkeypatch, tmp_path):
        _configured_patches(monkeypatch, tmp_path)
        with (
            patch(_PATCH_DASHBOARD_AVAILABLE, return_value=False),
            patch(_PATCH_DISPATCH, MagicMock()),
        ):
            result = runner.invoke(app, [], input=_FakeTTY(b"1\n"))
        assert result.exit_code == 0
        assert "Dashboard" not in result.output
        assert "Chat" in result.output
        assert "Create an agent" in result.output

    def test_enter_selects_chat(self, monkeypatch, tmp_path):
        _configured_patches(monkeypatch, tmp_path)
        mock_dispatch = MagicMock()
        with (
            patch(_PATCH_DASHBOARD_AVAILABLE, return_value=True),
            patch(_PATCH_DISPATCH, mock_dispatch),
        ):
            result = runner.invoke(app, [], input=_FakeTTY(b"\n"))
        assert result.exit_code == 0
        mock_dispatch.assert_called_once_with("chat")

    def test_chat_selected(self, monkeypatch, tmp_path):
        _configured_patches(monkeypatch, tmp_path)
        mock_dispatch = MagicMock()
        with (
            patch(_PATCH_DASHBOARD_AVAILABLE, return_value=True),
            patch(_PATCH_DISPATCH, mock_dispatch),
        ):
            result = runner.invoke(app, [], input=_FakeTTY(b"1\n"))
        assert result.exit_code == 0
        mock_dispatch.assert_called_once_with("chat")

    def test_starter_selected(self, monkeypatch, tmp_path):
        _configured_patches(monkeypatch, tmp_path)
        mock_dispatch = MagicMock()
        with (
            patch(_PATCH_DASHBOARD_AVAILABLE, return_value=False),
            patch(_PATCH_DISPATCH, mock_dispatch),
        ):
            result = runner.invoke(app, [], input=_FakeTTY(b"2\n"))
        assert result.exit_code == 0
        mock_dispatch.assert_called_once_with("starter")

    def test_new_selected(self, monkeypatch, tmp_path):
        _configured_patches(monkeypatch, tmp_path)
        mock_dispatch = MagicMock()
        with (
            patch(_PATCH_DASHBOARD_AVAILABLE, return_value=False),
            patch(_PATCH_DISPATCH, mock_dispatch),
        ):
            result = runner.invoke(app, [], input=_FakeTTY(b"3\n"))
        assert result.exit_code == 0
        mock_dispatch.assert_called_once_with("new")

    def test_dashboard_selected_when_last(self, monkeypatch, tmp_path):
        _configured_patches(monkeypatch, tmp_path)
        mock_dispatch = MagicMock()
        with (
            patch(_PATCH_DASHBOARD_AVAILABLE, return_value=True),
            patch(_PATCH_DISPATCH, mock_dispatch),
        ):
            result = runner.invoke(app, [], input=_FakeTTY(b"4\n"))
        assert result.exit_code == 0
        mock_dispatch.assert_called_once_with("dashboard")

    def test_ctrl_c_exits_clean(self, monkeypatch, tmp_path):
        _configured_patches(monkeypatch, tmp_path)
        with (
            patch(_PATCH_DASHBOARD_AVAILABLE, return_value=True),
            patch("rich.prompt.Prompt.ask", side_effect=KeyboardInterrupt),
        ):
            result = runner.invoke(app, [], input=_FakeTTY(b""))
        assert result.exit_code == 0
