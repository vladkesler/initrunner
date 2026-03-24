"""FastAPI dependency injection -- role cache, compose cache, team cache, and audit logger."""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Generic, TypeVar

from initrunner.dashboard.config import DashboardSettings

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

    def all(self) -> dict[str, T]:
        return self._cache


class RoleCache(_YamlFileCache["DiscoveredRole"]):
    """In-memory cache mapping opaque IDs to discovered roles."""

    def __init__(self, settings: DashboardSettings) -> None:
        from initrunner.services.discovery import discover_roles_sync

        super().__init__(settings, discover_roles_sync)


class ComposeCache(_YamlFileCache["DiscoveredCompose"]):
    """In-memory cache mapping opaque IDs to discovered compose definitions."""

    def __init__(self, settings: DashboardSettings) -> None:
        from initrunner.services.discovery import discover_composes_sync

        super().__init__(settings, discover_composes_sync)

    def refresh_one(self, compose_id: str, path: Path) -> None:
        """Re-load a single compose file from disk into the cache."""
        from initrunner.compose.loader import load_compose
        from initrunner.services.discovery import DiscoveredCompose

        try:
            comp = load_compose(path)
            self._cache[compose_id] = DiscoveredCompose(path=path, compose=comp)
        except Exception as exc:
            _logger.warning("Failed to reload compose %s: %s", compose_id, exc)
            self._cache[compose_id] = DiscoveredCompose(path=path, error=str(exc))


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


# -- Convenience aliases used by routers ---------------------------------------

_role_id = _file_id
_compose_id = _file_id
_team_id = _file_id


# -- Dependency placeholders (overridden in app factory) -----------------------


def get_role_cache() -> RoleCache:
    """Dependency placeholder -- overridden in app factory."""
    raise RuntimeError("RoleCache not initialized")


def get_compose_cache() -> ComposeCache:
    """Dependency placeholder -- overridden in app factory."""
    raise RuntimeError("ComposeCache not initialized")


def get_team_cache() -> TeamCache:
    """Dependency placeholder -- overridden in app factory."""
    raise RuntimeError("TeamCache not initialized")
