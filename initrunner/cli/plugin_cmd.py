"""Plugin command: list discovered tool plugins."""

from __future__ import annotations

from typing import Annotated  # noqa: F401

import typer  # noqa: F401
from rich.table import Table

from initrunner.cli._helpers import console


def plugins() -> None:
    """List discovered tool plugins."""
    from initrunner.agent.plugins import get_registry

    registry = get_registry()
    all_plugins = registry.list_plugins()

    if not all_plugins:
        console.print("No tool plugins installed.")
        console.print("[dim]Install plugins with: pip install initrunner-<plugin-name>[/dim]")
        return

    table = Table(title="Tool Plugins")
    table.add_column("Type", style="cyan")
    table.add_column("Description")
    table.add_column("Config Schema")

    for tool_type, plugin in sorted(all_plugins.items()):
        schema_name = plugin.config_class.__name__
        table.add_row(tool_type, plugin.description or "(none)", schema_name)

    console.print(table)
