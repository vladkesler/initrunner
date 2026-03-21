"""Tests for the CLI ``plugins`` command."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from pydantic import BaseModel
from typer.testing import CliRunner

from initrunner.cli.main import app

runner = CliRunner()


class TestPluginsEmptyState:
    @patch("initrunner.agent.plugins.get_registry")
    def test_no_plugins_message(self, mock_registry: MagicMock) -> None:
        registry = MagicMock()
        registry.list_plugins.return_value = {}
        mock_registry.return_value = registry

        result = runner.invoke(app, ["plugins"])

        assert result.exit_code == 0
        assert "No tool plugins installed" in result.output

    @patch("initrunner.agent.plugins.get_registry")
    def test_no_plugins_shows_docs_pointer(self, mock_registry: MagicMock) -> None:
        registry = MagicMock()
        registry.list_plugins.return_value = {}
        mock_registry.return_value = registry

        result = runner.invoke(app, ["plugins"])

        assert "docs/agents/tool_creation.md" in result.output

    @patch("initrunner.agent.plugins.get_registry")
    def test_no_plugins_shows_install_pattern(self, mock_registry: MagicMock) -> None:
        registry = MagicMock()
        registry.list_plugins.return_value = {}
        mock_registry.return_value = registry

        result = runner.invoke(app, ["plugins"])

        assert "pip install initrunner-<plugin-name>" in result.output


class _DummyConfig(BaseModel):
    type: str = "dummy"


class TestPluginsWithEntries:
    @patch("initrunner.agent.plugins.get_registry")
    def test_table_rendered(self, mock_registry: MagicMock) -> None:
        from initrunner.agent.plugins import ToolPlugin

        plugin = ToolPlugin(
            type="dummy",
            config_class=_DummyConfig,
            builder=lambda *a, **kw: None,
            description="A dummy plugin",
        )
        registry = MagicMock()
        registry.list_plugins.return_value = {"dummy": plugin}
        mock_registry.return_value = registry

        result = runner.invoke(app, ["plugins"])

        assert result.exit_code == 0
        assert "dummy" in result.output
        assert "A dummy plugin" in result.output
