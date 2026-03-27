"""Tests for the no-arg CLI entry menu (Dashboard / Quick chat / Create agent)."""

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


# Lazy imports in main.py mean we must patch at the source module, not at
# initrunner.cli.main.<name>.
_PATCH_DASHBOARD_AVAILABLE = "initrunner._compat.is_dashboard_available"
_PATCH_DISPATCH = "initrunner.cli._ephemeral.dispatch_ephemeral"
_PATCH_LAUNCH_DASHBOARD = "initrunner.cli.dashboard_cmd.launch_dashboard"
_PATCH_NEW = "initrunner.cli.new_cmd.new"
_PATCH_NEEDS_SETUP = "initrunner.services.setup.needs_setup"


def _configured_patches(monkeypatch, tmp_path):
    """Set up env for a configured provider."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("INITRUNNER_HOME", str(tmp_path / "home"))
    from initrunner.config import get_home_dir

    get_home_dir.cache_clear()


class TestDefaultEntryMenu:
    def test_dashboard_available_three_options(self, monkeypatch, tmp_path):
        """When dashboard is available, all 3 options are shown."""
        _configured_patches(monkeypatch, tmp_path)
        mock_dispatch = MagicMock()
        with (
            patch(_PATCH_DASHBOARD_AVAILABLE, return_value=True),
            patch(_PATCH_DISPATCH, mock_dispatch),
        ):
            result = runner.invoke(app, [], input=_FakeTTY(b"2\n"))
        assert result.exit_code == 0
        assert "Dashboard" in result.output
        assert "Quick chat" in result.output
        assert "Create an agent" in result.output

    def test_dashboard_unavailable_two_options(self, monkeypatch, tmp_path):
        """When dashboard is unavailable, only 2 options shown."""
        _configured_patches(monkeypatch, tmp_path)
        mock_dispatch = MagicMock()
        with (
            patch(_PATCH_DASHBOARD_AVAILABLE, return_value=False),
            patch(_PATCH_DISPATCH, mock_dispatch),
        ):
            result = runner.invoke(app, [], input=_FakeTTY(b"1\n"))
        assert result.exit_code == 0
        assert "Dashboard" not in result.output
        assert "Quick chat" in result.output
        assert "Create an agent" in result.output

    def test_dashboard_selected_launches_dashboard(self, monkeypatch, tmp_path):
        """Selecting Dashboard calls launch_dashboard()."""
        _configured_patches(monkeypatch, tmp_path)
        mock_launch = MagicMock()
        with (
            patch(_PATCH_DASHBOARD_AVAILABLE, return_value=True),
            patch(_PATCH_LAUNCH_DASHBOARD, mock_launch),
        ):
            result = runner.invoke(app, [], input=_FakeTTY(b"1\n"))
        assert result.exit_code == 0
        mock_launch.assert_called_once()

    def test_repl_selected_launches_dispatch(self, monkeypatch, tmp_path):
        """Selecting Quick chat calls dispatch_ephemeral()."""
        _configured_patches(monkeypatch, tmp_path)
        mock_dispatch = MagicMock()
        with (
            patch(_PATCH_DASHBOARD_AVAILABLE, return_value=True),
            patch(_PATCH_DISPATCH, mock_dispatch),
        ):
            result = runner.invoke(app, [], input=_FakeTTY(b"2\n"))
        assert result.exit_code == 0
        mock_dispatch.assert_called_once()

    def test_new_selected_launches_new(self, monkeypatch, tmp_path):
        """Selecting 'Create an agent' calls new()."""
        _configured_patches(monkeypatch, tmp_path)
        mock_new = MagicMock()
        with (
            patch(_PATCH_DASHBOARD_AVAILABLE, return_value=False),
            patch(_PATCH_NEW, mock_new),
        ):
            result = runner.invoke(app, [], input=_FakeTTY(b"2\n"))
        assert result.exit_code == 0
        mock_new.assert_called_once()

    def test_repl_shows_bot_hint(self, monkeypatch, tmp_path):
        """Bot token hint appears when REPL is selected and tokens are set."""
        _configured_patches(monkeypatch, tmp_path)
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")

        mock_dispatch = MagicMock()
        with (
            patch(_PATCH_DASHBOARD_AVAILABLE, return_value=False),
            patch(_PATCH_DISPATCH, mock_dispatch),
        ):
            result = runner.invoke(app, [], input=_FakeTTY(b"1\n"))
        assert result.exit_code == 0
        assert "bot tokens detected" in result.output

    def test_ctrl_c_exits_clean(self, monkeypatch, tmp_path):
        """KeyboardInterrupt during menu exits cleanly."""
        _configured_patches(monkeypatch, tmp_path)
        with (
            patch(_PATCH_DASHBOARD_AVAILABLE, return_value=True),
            patch("rich.prompt.Prompt.ask", side_effect=KeyboardInterrupt),
        ):
            result = runner.invoke(app, [], input=_FakeTTY(b""))
        assert result.exit_code == 0
