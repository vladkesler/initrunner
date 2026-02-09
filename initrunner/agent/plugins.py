"""Plugin registry for third-party tool packages."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from pydantic import BaseModel

_logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from pydantic_ai.toolsets import AbstractToolset


@dataclass
class ToolPlugin:
    """A registered tool plugin."""

    type: str  # discriminator value (e.g. "slack")
    config_class: type[BaseModel]  # Pydantic config schema
    builder: Callable[..., AbstractToolset]  # (validated_config, **kw) -> toolset
    description: str = ""


@dataclass
class PluginRegistry:
    """Registry for tool plugins, with lazy entry point discovery."""

    _plugins: dict[str, ToolPlugin] = field(default_factory=dict)
    _discovered: bool = False

    def register(self, plugin: ToolPlugin) -> None:
        """Register a tool plugin."""
        self._plugins[plugin.type] = plugin

    def _discover(self) -> None:
        """Discover plugins via entry points (lazy, called once)."""
        if self._discovered:
            return
        self._discovered = True

        from importlib.metadata import entry_points

        eps = entry_points(group="initrunner.tools")
        for ep in eps:
            try:
                factory = ep.load()
                plugin = factory()
                if isinstance(plugin, ToolPlugin):
                    self._plugins.setdefault(plugin.type, plugin)
            except Exception:
                _logger.warning("Failed to load plugin %s: %s", ep.name, ep, exc_info=True)

    def get(self, tool_type: str) -> ToolPlugin | None:
        """Get a plugin by type, discovering entry points on first call."""
        self._discover()
        return self._plugins.get(tool_type)

    def list_plugins(self) -> dict[str, ToolPlugin]:
        """List all registered plugins."""
        self._discover()
        return dict(self._plugins)


_registry: PluginRegistry | None = None


def get_registry() -> PluginRegistry:
    """Get or create the global plugin registry."""
    global _registry
    if _registry is None:
        _registry = PluginRegistry()
    return _registry
