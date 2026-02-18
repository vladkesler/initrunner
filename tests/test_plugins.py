"""Tests for the plugin registry."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from pydantic import BaseModel
from pydantic_ai.toolsets.function import FunctionToolset

from initrunner.agent.plugins import PluginRegistry, ToolPlugin
from initrunner.agent.schema.tools import PluginToolConfig
from initrunner.agent.tools import _build_plugin_toolset
from initrunner.agent.tools._registry import ToolBuildContext


def _make_ctx(role_dir=None):
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
    return ToolBuildContext(role=role, role_dir=role_dir)


class DummyConfig(BaseModel):
    type: str = "dummy"
    api_key: str = ""


def _dummy_builder(config: DummyConfig, **kwargs: object) -> FunctionToolset:
    toolset = FunctionToolset()

    @toolset.tool
    def dummy_tool(query: str) -> str:
        """A dummy tool."""
        return f"dummy: {query}"

    return toolset


class TestPluginRegistry:
    def test_register_and_get(self):
        registry = PluginRegistry()
        plugin = ToolPlugin(
            type="dummy",
            config_class=DummyConfig,
            builder=_dummy_builder,
            description="A dummy plugin",
        )
        registry.register(plugin)
        assert registry.get("dummy") is plugin

    def test_get_unknown_returns_none(self):
        registry = PluginRegistry()
        registry._discovered = True  # skip entry point discovery
        assert registry.get("nonexistent") is None

    def test_list_plugins(self):
        registry = PluginRegistry()
        registry._discovered = True
        plugin = ToolPlugin(type="test", config_class=DummyConfig, builder=_dummy_builder)
        registry.register(plugin)
        plugins = registry.list_plugins()
        assert "test" in plugins
        assert plugins["test"] is plugin

    def test_entry_point_discovery(self):
        """Mocked entry point discovery loads plugins."""
        registry = PluginRegistry()

        mock_ep = MagicMock()
        mock_ep.load.return_value = lambda: ToolPlugin(
            type="slack",
            config_class=DummyConfig,
            builder=_dummy_builder,
            description="Slack integration",
        )

        with patch("importlib.metadata.entry_points", return_value=[mock_ep]):
            result = registry.get("slack")

        assert result is not None
        assert result.type == "slack"
        assert result.description == "Slack integration"

    def test_broken_entry_point_skipped(self):
        """Broken entry points are silently skipped."""
        registry = PluginRegistry()

        mock_ep = MagicMock()
        mock_ep.load.side_effect = ImportError("broken")

        with patch("importlib.metadata.entry_points", return_value=[mock_ep]):
            result = registry.get("anything")

        assert result is None

    def test_discovery_runs_once(self):
        """Entry point discovery only runs on first get() call."""
        registry = PluginRegistry()

        with patch("importlib.metadata.entry_points", return_value=[]) as mock:
            registry.get("a")
            registry.get("b")

        mock.assert_called_once()


class TestBuildPluginToolset:
    def test_unknown_type_no_plugins(self):
        """Unknown type with no plugins gives helpful error."""
        config = PluginToolConfig(type="unknown_xyz")
        # Use a fresh registry with no plugins
        registry = PluginRegistry()
        registry._discovered = True

        with patch("initrunner.agent.plugins.get_registry", return_value=registry):
            with pytest.raises(ValueError, match="No plugins installed"):
                _build_plugin_toolset(config, _make_ctx())

    def test_unknown_type_with_installed_plugins(self):
        """Unknown type with installed plugins lists them."""
        config = PluginToolConfig(type="unknown_xyz")
        registry = PluginRegistry()
        registry._discovered = True
        registry.register(
            ToolPlugin(type="slack", config_class=DummyConfig, builder=_dummy_builder)
        )
        registry.register(ToolPlugin(type="jira", config_class=DummyConfig, builder=_dummy_builder))

        with patch("initrunner.agent.plugins.get_registry", return_value=registry):
            with pytest.raises(ValueError, match=r"Installed plugins:.*jira.*slack"):
                _build_plugin_toolset(config, _make_ctx())

    def test_config_validation_against_plugin_schema(self):
        """Config is validated against the plugin's config class."""

        class StrictConfig(BaseModel):
            type: str = "strict"
            required_key: str  # required field

        registry = PluginRegistry()
        registry._discovered = True
        registry.register(
            ToolPlugin(type="strict", config_class=StrictConfig, builder=_dummy_builder)
        )

        # Missing required_key should raise
        config = PluginToolConfig(type="strict", config={})
        with patch("initrunner.agent.plugins.get_registry", return_value=registry):
            with pytest.raises(Exception):  # noqa: B017
                _build_plugin_toolset(config, _make_ctx())

    def test_successful_build(self):
        """Valid plugin config builds a toolset."""
        config = PluginToolConfig(type="dummy", config={"api_key": "test123"})
        registry = PluginRegistry()
        registry._discovered = True
        registry.register(
            ToolPlugin(
                type="dummy",
                config_class=DummyConfig,
                builder=_dummy_builder,
                description="Dummy",
            )
        )

        with patch("initrunner.agent.plugins.get_registry", return_value=registry):
            toolset = _build_plugin_toolset(config, _make_ctx())

        assert toolset is not None
        assert "dummy_tool" in toolset.tools  # type: ignore[attr-defined]
