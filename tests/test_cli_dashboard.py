"""Tests for ``initrunner dashboard`` CLI command."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from initrunner.cli.main import app

runner = CliRunner()

_PATCH_LAUNCH = "initrunner.cli.dashboard_cmd.launch_dashboard"


class TestDashboardApiKeyEnvVar:
    """INITRUNNER_DASHBOARD_API_KEY env var populates --api-key."""

    def test_env_var_sets_api_key(self, monkeypatch):
        monkeypatch.setenv("INITRUNNER_DASHBOARD_API_KEY", "secret-from-env")
        mock_launch = MagicMock()
        with patch(_PATCH_LAUNCH, mock_launch):
            result = runner.invoke(app, ["dashboard", "--no-open"])
        assert result.exit_code == 0
        mock_launch.assert_called_once()
        assert mock_launch.call_args.kwargs["api_key"] == "secret-from-env"

    def test_flag_overrides_env_var(self, monkeypatch):
        monkeypatch.setenv("INITRUNNER_DASHBOARD_API_KEY", "from-env")
        mock_launch = MagicMock()
        with patch(_PATCH_LAUNCH, mock_launch):
            result = runner.invoke(app, ["dashboard", "--no-open", "--api-key", "from-flag"])
        assert result.exit_code == 0
        mock_launch.assert_called_once()
        assert mock_launch.call_args.kwargs["api_key"] == "from-flag"

    def test_no_env_no_flag_gives_none(self, monkeypatch):
        monkeypatch.delenv("INITRUNNER_DASHBOARD_API_KEY", raising=False)
        mock_launch = MagicMock()
        with patch(_PATCH_LAUNCH, mock_launch):
            result = runner.invoke(app, ["dashboard", "--no-open"])
        assert result.exit_code == 0
        mock_launch.assert_called_once()
        assert mock_launch.call_args.kwargs["api_key"] is None
