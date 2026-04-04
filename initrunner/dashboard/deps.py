"""FastAPI dependency injection -- role cache, flow cache, team cache, and audit logger."""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Generic, TypeVar

from initrunner.dashboard.config import DashboardSettings

if TYPE_CHECKING:
    from initrunner.services.discovery import (  # noqa: F401
        DiscoveredFlow,
        DiscoveredRole,
        DiscoveredTeam,
    )
    from initrunner.services.skill_service import DiscoveredSkillFull

_logger = logging.getLogger(__name__)

T = TypeVar("T")


def _file_id(path: Path) -> str:
    """Derive a stable opaque ID from a file's resolved path."""
    return hashlib.sha256(str(path.resolve()).encode()).hexdigest()[:12]


class _YamlFileCache(Generic[T]):
    """Base cache mapping opaque IDs to discovered YAML resources."""

    _kind: str = ""

    def __init__(
        self,
        settings: DashboardSettings,
        discover_fn: Callable[[list[Path]], list[T]],
        path_attr: str = "path",
    ) -> None:
        self._settings = settings
        self._discover_fn = discover_fn
        self._path_attr = path_attr
        self._cache: dict[str, T] = {}

    def refresh(self) -> dict[str, T]:
        items = self._discover_fn(self._settings.get_role_dirs())
        self._cache = {_file_id(getattr(item, self._path_attr)): item for item in items}
        _logger.debug("%s refreshed: %d items", type(self).__name__, len(self._cache))
        return self._cache

    def get(self, item_id: str) -> T | None:
        return self._cache.get(item_id)

    def evict(self, item_id: str) -> T | None:
        """Remove an item from the cache by ID. Returns the evicted item, or None."""
        return self._cache.pop(item_id, None)

    def all(self) -> dict[str, T]:
        return self._cache


class RoleCache(_YamlFileCache["DiscoveredRole"]):
    """In-memory cache mapping opaque IDs to discovered roles."""

    def __init__(self, settings: DashboardSettings) -> None:
        from initrunner.services.discovery import discover_roles_sync

        super().__init__(settings, discover_roles_sync)


class FlowCache(_YamlFileCache["DiscoveredFlow"]):
    """In-memory cache mapping opaque IDs to discovered flow definitions."""

    def __init__(self, settings: DashboardSettings) -> None:
        from initrunner.services.discovery import discover_flows_sync

        super().__init__(settings, discover_flows_sync)

    def refresh_one(self, flow_id: str, path: Path) -> None:
        """Re-load a single flow file from disk into the cache."""
        from initrunner.flow.loader import load_flow
        from initrunner.services.discovery import DiscoveredFlow

        try:
            comp = load_flow(path)
            self._cache[flow_id] = DiscoveredFlow(path=path, flow=comp)
        except Exception as exc:
            _logger.warning("Failed to reload flow %s: %s", flow_id, exc)
            self._cache[flow_id] = DiscoveredFlow(path=path, error=str(exc))


class TeamCache(_YamlFileCache["DiscoveredTeam"]):
    """In-memory cache mapping opaque IDs to discovered team definitions."""

    def __init__(self, settings: DashboardSettings) -> None:
        from initrunner.services.discovery import discover_teams_sync

        super().__init__(settings, discover_teams_sync)

    def refresh_one(self, team_id: str, path: Path) -> None:
        """Re-load a single team file from disk into the cache."""
        from initrunner.services.discovery import DiscoveredTeam
        from initrunner.team.loader import load_team

        try:
            team = load_team(path)
            self._cache[team_id] = DiscoveredTeam(path=path, team=team)
        except Exception as exc:
            _logger.warning("Failed to reload team %s: %s", team_id, exc)
            self._cache[team_id] = DiscoveredTeam(path=path, error=str(exc))


class SkillCache(_YamlFileCache["DiscoveredSkillFull"]):
    """In-memory cache mapping opaque IDs to discovered skills.

    Overrides ``refresh()`` because skill discovery uses different search
    paths than ``get_role_dirs()`` alone.
    """

    def __init__(self, settings: DashboardSettings) -> None:
        super().__init__(settings, lambda dirs: [], path_attr="path")

    def refresh(self) -> dict[str, DiscoveredSkillFull]:
        from initrunner.services.skill_service import discover_skills_full

        items = discover_skills_full(self._settings.get_role_dirs())
        self._cache = {_file_id(item.path): item for item in items}
        _logger.debug("SkillCache refreshed: %d items", len(self._cache))
        return self._cache

    def refresh_one(self, skill_id: str, path: Path) -> None:
        """Re-load a single skill file from disk into the cache."""
        from initrunner.services.skill_service import load_skill_full

        try:
            self._cache[skill_id] = load_skill_full(path)
        except Exception as exc:
            _logger.warning("Failed to reload skill %s: %s", skill_id, exc)


# -- Convenience aliases used by routers ---------------------------------------

_role_id = _file_id
_flow_id = _file_id
_team_id = _file_id
_skill_id = _file_id


# -- Dependency placeholders (overridden in app factory) -----------------------


def get_role_cache() -> RoleCache:
    """Dependency placeholder -- overridden in app factory."""
    raise RuntimeError("RoleCache not initialized")


def get_flow_cache() -> FlowCache:
    """Dependency placeholder -- overridden in app factory."""
    raise RuntimeError("FlowCache not initialized")


def get_team_cache() -> TeamCache:
    """Dependency placeholder -- overridden in app factory."""
    raise RuntimeError("TeamCache not initialized")


def get_skill_cache() -> SkillCache:
    """Dependency placeholder -- overridden in app factory."""
    raise RuntimeError("SkillCache not initialized")
