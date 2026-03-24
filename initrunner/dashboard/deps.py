"""FastAPI dependency injection -- role cache, compose cache, and audit logger."""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from initrunner.services.discovery import DiscoveredCompose, DiscoveredRole

from initrunner.dashboard.config import DashboardSettings

_logger = logging.getLogger(__name__)


def _role_id(path: Path) -> str:
    """Derive a stable opaque ID from a role file's resolved path."""
    return hashlib.sha256(str(path.resolve()).encode()).hexdigest()[:12]


def _compose_id(path: Path) -> str:
    """Derive a stable opaque ID from a compose file's resolved path."""
    return hashlib.sha256(str(path.resolve()).encode()).hexdigest()[:12]


class RoleCache:
    """In-memory cache mapping opaque IDs to discovered roles."""

    def __init__(self, settings: DashboardSettings) -> None:
        self._settings = settings
        self._cache: dict[str, DiscoveredRole] = {}

    def refresh(self) -> dict[str, DiscoveredRole]:
        from initrunner.services.discovery import discover_roles_sync

        roles = discover_roles_sync(self._settings.get_role_dirs())
        self._cache = {_role_id(r.path): r for r in roles}
        _logger.debug("RoleCache refreshed: %d roles", len(self._cache))
        return self._cache

    def get(self, role_id: str) -> DiscoveredRole | None:
        return self._cache.get(role_id)

    def all(self) -> dict[str, DiscoveredRole]:
        return self._cache


class ComposeCache:
    """In-memory cache mapping opaque IDs to discovered compose definitions."""

    def __init__(self, settings: DashboardSettings) -> None:
        self._settings = settings
        self._cache: dict[str, DiscoveredCompose] = {}

    def refresh(self) -> dict[str, DiscoveredCompose]:
        from initrunner.services.discovery import discover_composes_sync

        composes = discover_composes_sync(self._settings.get_role_dirs())
        self._cache = {_compose_id(c.path): c for c in composes}
        _logger.debug("ComposeCache refreshed: %d composes", len(self._cache))
        return self._cache

    def get(self, compose_id: str) -> DiscoveredCompose | None:
        return self._cache.get(compose_id)

    def all(self) -> dict[str, DiscoveredCompose]:
        return self._cache


def get_role_cache() -> RoleCache:
    """Dependency placeholder -- overridden in app factory."""
    raise RuntimeError("RoleCache not initialized")


def get_compose_cache() -> ComposeCache:
    """Dependency placeholder -- overridden in app factory."""
    raise RuntimeError("ComposeCache not initialized")
