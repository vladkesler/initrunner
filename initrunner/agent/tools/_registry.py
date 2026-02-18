"""Self-registering tool registry with auto-discovery.

Each tool module decorates its builder with ``@register_tool``.  At first
access the discovery step imports every module under ``initrunner.agent.tools``
(skipping ``_``-prefixed) **plus** a list of legacy modules that live one
level up.  This populates two dicts — ``type → config class`` and
``type → builder`` — so that ``parse_tool_list()`` and ``build_toolsets()``
never need hardcoded mappings.
"""

from __future__ import annotations

import importlib
import logging
import pkgutil
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypeVar

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from pydantic_ai.toolsets import AbstractToolset

    from initrunner.agent.schema.role import RoleDefinition
    from initrunner.agent.schema.tools import ToolConfigBase

# ---------------------------------------------------------------------------
# Build context passed to every builder
# ---------------------------------------------------------------------------


@dataclass
class ToolBuildContext:
    """Shared context passed to all tool builders."""

    role: RoleDefinition
    role_dir: Path | None = None


# ---------------------------------------------------------------------------
# Registration dataclass and global registries
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ToolRegistration:
    type: str
    config_class: type[ToolConfigBase]
    builder: Callable[..., AbstractToolset]


_tool_registry: dict[str, ToolRegistration] = {}
_registry_lock = threading.Lock()


_F = TypeVar("_F", bound=Callable[..., "AbstractToolset"])


def register_tool(type_name: str, config_class: type[Any]) -> Callable[[_F], _F]:
    """Decorator that registers a tool builder.

    Usage::

        @register_tool("datetime", DateTimeToolConfig)
        def build_datetime_toolset(config, ctx):
            ...
    """

    def decorator(func: _F) -> _F:
        # Validate type field default matches type_name (skip if no default)
        from pydantic_core import PydanticUndefined

        field_info = config_class.model_fields.get("type")
        if (
            field_info is not None
            and field_info.default is not PydanticUndefined
            and field_info.default != type_name
        ):
            raise ValueError(
                f"register_tool('{type_name}', {config_class.__name__}): "
                f"config class type field default is '{field_info.default}', "
                f"expected '{type_name}'"
            )

        _tool_registry[type_name] = ToolRegistration(
            type=type_name,
            config_class=config_class,
            builder=func,
        )
        return func

    return decorator


# ---------------------------------------------------------------------------
# Auto-discovery
# ---------------------------------------------------------------------------

# Modules outside of initrunner.agent.tools that contain @register_tool
_LEGACY_TOOL_MODULES: list[str] = [
    "initrunner.agent.git_tools",
    "initrunner.agent.python_tools",
    "initrunner.agent.sql_tools",
    "initrunner.agent.shell_tools",
    "initrunner.agent.slack_tools",
    "initrunner.agent.api_tools",
    "initrunner.mcp.server",
]

_discovered_modules: set[str] = set()
_all_discovered: bool = False


def _ensure_discovered() -> None:
    """Import all tool modules to trigger ``@register_tool`` decorators.

    Tracks per-module success so that failed imports are retried on the
    next call.  Once every module has been imported successfully the fast
    path (``_all_discovered``) avoids any further work.
    """
    global _all_discovered
    if _all_discovered:
        return

    with _registry_lock:
        if _all_discovered:
            return

        # Enumerate all expected modules
        import initrunner.agent.tools as _pkg

        all_modules: list[str] = []
        for _importer, modname, _ispkg in pkgutil.iter_modules(_pkg.__path__):
            if modname.startswith("_"):
                continue
            all_modules.append(f"initrunner.agent.tools.{modname}")

        all_modules.extend(_LEGACY_TOOL_MODULES)

        pending = [m for m in all_modules if m not in _discovered_modules]
        if not pending:
            _all_discovered = True
            return

        for mod_path in pending:
            try:
                importlib.import_module(mod_path)
                _discovered_modules.add(mod_path)
            except Exception as exc:
                logger.error("Failed to import tool module %s: %s", mod_path, exc)

        if _discovered_modules.issuperset(all_modules):
            _all_discovered = True


def _reset_discovery() -> None:
    """Reset discovery state. Intended for test teardown only."""
    global _all_discovered
    with _registry_lock:
        _discovered_modules.clear()
        _all_discovered = False


# ---------------------------------------------------------------------------
# Public query API
# ---------------------------------------------------------------------------


def get_tool_types() -> dict[str, type[ToolConfigBase]]:
    """Return ``{type_name: config_class}`` for all registered tools."""
    _ensure_discovered()
    return {name: reg.config_class for name, reg in _tool_registry.items()}


def get_builder(type_name: str) -> Callable[..., AbstractToolset] | None:
    """Return the registered builder for *type_name*, or ``None``."""
    _ensure_discovered()
    reg = _tool_registry.get(type_name)
    return reg.builder if reg else None
