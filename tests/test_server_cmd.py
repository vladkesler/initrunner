"""Tests for auto-install prompts in tui/ui commands."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import click
import pytest
from typer.testing import CliRunner

from initrunner.cli.main import app

runner = CliRunner()


class TestTuiAutoInstall:
    """Tests for the tui command auto-install prompt."""

    def test_tui_offers_install_on_missing_dep(self):
        """When textual is missing and user accepts, should call install_extra."""
        from initrunner.cli.server_cmd import tui as tui_cmd

        with (
            patch.dict("sys.modules", {"textual": None}),
            patch("initrunner.cli._helpers.install_extra", return_value=False) as mock_install,
            patch("sys.stdin") as mock_stdin,
            patch("initrunner.cli.server_cmd.typer.confirm", return_value=True),
            pytest.raises(click.exceptions.Exit),
        ):
            mock_stdin.isatty.return_value = True
            tui_cmd(role_dir=None)

        mock_install.assert_called_once_with("tui")

    def test_tui_decline_install_exits(self):
        """Declining install exits with code 1."""
        with (
            patch.dict("sys.modules", {"textual": None}),
            patch("sys.stdin") as mock_stdin,
        ):
            mock_stdin.isatty.return_value = True
            result = runner.invoke(app, ["tui"], input="n\n")

        assert result.exit_code == 1

    def test_tui_noninteractive_exits(self):
        """Non-interactive environment prints manual hint and exits."""
        with patch.dict("sys.modules", {"textual": None}):
            result = runner.invoke(app, ["tui"])

        assert result.exit_code == 1
        assert "Install manually" in result.output


class TestUiAutoInstall:
    """Tests for the ui command auto-install prompt."""

    def test_ui_offers_install_on_missing_dep(self):
        """When dashboard deps are missing and user accepts, should call install_extra."""
        from initrunner.cli.server_cmd import ui as ui_cmd

        with (
            patch.dict("sys.modules", {"initrunner.api.app": None}),
            patch("initrunner.cli._helpers.install_extra", return_value=False) as mock_install,
            patch("sys.stdin") as mock_stdin,
            patch("initrunner.cli.server_cmd.typer.confirm", return_value=True),
            pytest.raises(click.exceptions.Exit),
        ):
            mock_stdin.isatty.return_value = True
            ui_cmd(role_dir=None)

        mock_install.assert_called_once_with("dashboard")

    def test_ui_decline_install_exits(self):
        """Declining install exits with code 1."""
        with (
            patch.dict("sys.modules", {"initrunner.api.app": None}),
            patch("sys.stdin") as mock_stdin,
        ):
            mock_stdin.isatty.return_value = True
            result = runner.invoke(app, ["ui"], input="n\n")

        assert result.exit_code == 1

    def test_ui_noninteractive_exits(self):
        """Non-interactive environment prints manual hint and exits."""
        with patch.dict("sys.modules", {"initrunner.api.app": None}):
            result = runner.invoke(app, ["ui"])

        assert result.exit_code == 1
        assert "Install manually" in result.output


class TestUiAuditLogger:
    """Tests for audit logger creation in the ui command."""

    def test_ui_creates_and_passes_audit_logger(self):
        """ui() should create an audit logger and pass it to run_dashboard."""
        from initrunner.cli.server_cmd import ui as ui_cmd

        mock_logger = MagicMock()

        with (
            patch("initrunner.cli.server_cmd._resolve_dashboard_key", return_value=None),
            patch(
                "initrunner.cli.server_cmd.create_audit_logger", return_value=mock_logger
            ) as mock_create,
            patch("atexit.register") as mock_atexit,
            patch("initrunner.api.app.run_dashboard") as mock_run,
        ):
            ui_cmd(role_dir=None)

        mock_create.assert_called_once_with(None, False)
        mock_atexit.assert_called_once_with(mock_logger.close)
        assert mock_run.call_args.kwargs["audit_logger"] is mock_logger

    def test_ui_no_audit_skips_logger(self):
        """ui(no_audit=True) should pass None audit_logger to run_dashboard."""
        from initrunner.cli.server_cmd import ui as ui_cmd

        with (
            patch("initrunner.cli.server_cmd._resolve_dashboard_key", return_value=None),
            patch(
                "initrunner.cli.server_cmd.create_audit_logger", return_value=None
            ) as mock_create,
            patch("atexit.register") as mock_atexit,
            patch("initrunner.api.app.run_dashboard") as mock_run,
        ):
            ui_cmd(role_dir=None, no_audit=True)

        mock_create.assert_called_once_with(None, True)
        mock_atexit.assert_not_called()
        assert mock_run.call_args.kwargs["audit_logger"] is None


class TestResolveDashboardKeyDocker:
    """Tests for Docker auth bypass in _resolve_dashboard_key."""

    def test_docker_auto_generates_key_for_non_localhost(self, tmp_path):
        """When _DOCKER=True, binding to 0.0.0.0 should auto-generate a key."""
        from initrunner.cli.server_cmd import _resolve_dashboard_key

        with (
            patch("initrunner.cli.server_cmd._DOCKER", True),
            patch.dict("os.environ", {}, clear=True),
            patch("pathlib.Path.home", return_value=tmp_path),
        ):
            key = _resolve_dashboard_key(None, False, "0.0.0.0")

        assert key is not None
        assert len(key) > 0
        # Key should be persisted
        assert (tmp_path / ".initrunner" / "dashboard.key").read_text() == key

    def test_non_docker_blocks_non_localhost(self):
        """When _DOCKER=False, binding to 0.0.0.0 should raise SystemExit."""
        from initrunner.cli.server_cmd import _resolve_dashboard_key

        with (
            patch("initrunner.cli.server_cmd._DOCKER", False),
            patch.dict("os.environ", {}, clear=True),
            pytest.raises(click.exceptions.Exit),
        ):
            _resolve_dashboard_key(None, False, "0.0.0.0")


class TestDefaultUiHost:
    """Tests for Docker-aware default host detection."""

    def test_default_host_in_docker(self):
        """When /.dockerenv exists, default host should be 0.0.0.0."""
        with patch("initrunner.cli.server_cmd.Path.exists", return_value=True):
            import initrunner.cli.server_cmd as mod

            # Re-evaluate the module-level constants
            mod._DOCKER = mod.Path("/.dockerenv").exists()
            mod._DEFAULT_UI_HOST = "0.0.0.0" if mod._DOCKER else "127.0.0.1"

            assert mod._DOCKER is True
            assert mod._DEFAULT_UI_HOST == "0.0.0.0"

    def test_default_host_outside_docker(self):
        """When /.dockerenv does not exist, default host should be 127.0.0.1."""
        with patch("initrunner.cli.server_cmd.Path.exists", return_value=False):
            import initrunner.cli.server_cmd as mod

            mod._DOCKER = mod.Path("/.dockerenv").exists()
            mod._DEFAULT_UI_HOST = "0.0.0.0" if mod._DOCKER else "127.0.0.1"

            assert mod._DOCKER is False
            assert mod._DEFAULT_UI_HOST == "127.0.0.1"
