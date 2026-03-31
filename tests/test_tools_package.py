"""Regression: tools package split preserves API surface and subclass registration."""

from __future__ import annotations

import initrunner.agent.schema.tools as tools_pkg
from initrunner.agent.schema.tools import (
    DelegateToolConfig,
    PluginToolConfig,
    ShellToolConfig,
    SpawnToolConfig,
    ToolConfig,
    ToolConfigBase,
    ToolPermissions,
)


class TestToolsPackageAPI:
    """Importing the package must bind every public name and register subclasses."""

    def test_representative_exports_are_bound(self) -> None:
        assert tools_pkg.ShellToolConfig is ShellToolConfig
        assert tools_pkg.ToolPermissions is ToolPermissions
        assert tools_pkg.PluginToolConfig is PluginToolConfig

    def test_all_matches_dir(self) -> None:
        assert hasattr(tools_pkg, "__all__")
        for name in tools_pkg.__all__:
            assert hasattr(tools_pkg, name), f"{name} in __all__ but not importable"

    def test_subclass_registration(self) -> None:
        subclasses = set(ToolConfigBase.__subclasses__())
        for cls in (ShellToolConfig, SpawnToolConfig, DelegateToolConfig, PluginToolConfig):
            assert cls in subclasses, f"{cls.__name__} missing from __subclasses__()"
        assert len(subclasses) >= 27

    def test_tool_config_alias(self) -> None:
        assert ToolConfig is ToolConfigBase


class TestPydanticAnnotationCompat:
    """ToolConfig in Pydantic annotations must still parse and validate."""

    def test_agent_spec_parses_tools(self) -> None:
        from initrunner.agent.schema.role import AgentSpec

        spec = AgentSpec(role="test", tools=[{"type": "shell"}])  # type: ignore[arg-type]
        assert len(spec.tools) == 1
        assert isinstance(spec.tools[0], ShellToolConfig)

    def test_team_spec_parses_tools(self) -> None:
        from initrunner.agent.schema.tools import DateTimeToolConfig
        from initrunner.team.schema import TeamSpec

        spec = TeamSpec(
            personas={"alice": "role a", "bob": "role b"},  # type: ignore[arg-type]
            tools=[{"type": "datetime"}],  # type: ignore[arg-type]
        )
        assert len(spec.tools) == 1
        assert isinstance(spec.tools[0], DateTimeToolConfig)
