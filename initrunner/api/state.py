"""In-memory session and agent state for the dashboard API."""

from __future__ import annotations

import base64
import hashlib
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pydantic_ai import Agent

    from initrunner.agent.schema import RoleDefinition

_SESSION_TTL = 3600  # 1 hour
_CLEANUP_INTERVAL = 300  # 5 minutes
_MAX_SESSIONS = 1000


@dataclass
class ChatSession:
    """Active chat session with agent and message history."""

    role_id: str
    agent: Agent
    role: RoleDefinition
    role_path: Path
    message_history: list = field(default_factory=list)
    last_active: float = field(default_factory=time.monotonic)


class SessionStore:
    """Thread-safe store for active chat sessions and cached agents."""

    def __init__(self) -> None:
        self._sessions: dict[str, ChatSession] = {}
        self._lock = threading.Lock()
        self._last_cleanup = time.monotonic()

    def get(self, session_id: str) -> ChatSession | None:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is not None:
                session.last_active = time.monotonic()
            return session

    def create(
        self,
        session_id: str,
        role_id: str,
        agent: Any,
        role: Any,
        role_path: Path,
        message_history: list | None = None,
    ) -> ChatSession:
        session = ChatSession(
            role_id=role_id,
            agent=agent,
            role=role,
            role_path=role_path,
            message_history=message_history or [],
        )
        with self._lock:
            if len(self._sessions) >= _MAX_SESSIONS:
                # Evict oldest by last_active
                oldest_id = min(self._sessions, key=lambda k: self._sessions[k].last_active)
                del self._sessions[oldest_id]
            self._sessions[session_id] = session
        self._maybe_cleanup()
        return session

    def remove(self, session_id: str) -> None:
        with self._lock:
            self._sessions.pop(session_id, None)

    def _maybe_cleanup(self) -> None:
        with self._lock:
            now = time.monotonic()
            if now - self._last_cleanup < _CLEANUP_INTERVAL:
                return
            self._last_cleanup = now
            expired = [
                sid for sid, s in self._sessions.items() if now - s.last_active > _SESSION_TTL
            ]
            for sid in expired:
                del self._sessions[sid]


# Singleton
sessions = SessionStore()


def role_path_to_id(path: Path) -> str:
    """Encode a role file path as a URL-safe ID."""
    digest = hashlib.sha256(str(path.resolve()).encode()).digest()[:12]
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


def find_role_path(role_id: str, search_dirs: list[Path] | None = None) -> Path | None:
    """Resolve a role ID to a filesystem path by scanning directories."""
    from initrunner.services import discover_roles_sync

    dirs = search_dirs or [Path(".")]
    for d in discover_roles_sync(dirs):
        if role_path_to_id(d.path) == role_id:
            return d.path
    return None


def id_to_role_path(role_id: str, known_roles: dict[str, Path]) -> Path | None:
    """Look up a role path from a role ID using the known roles registry."""
    return known_roles.get(role_id)


_CACHE_TTL = 30.0  # seconds


class RoleRegistry:
    """Cached role discovery backed by ``discover_roles_sync``.

    Stores results for ``_CACHE_TTL`` seconds so repeated API calls
    (list → detail → chat) don't each trigger a full directory scan.
    """

    def __init__(self, role_dirs: list[Path]) -> None:
        self.role_dirs = role_dirs
        self._lock = threading.Lock()
        self._cache: list | None = None
        self._cache_time: float = 0.0

    def discover(self):
        """Return cached discovery results, refreshing if stale."""
        from initrunner.services import DiscoveredRole, discover_roles_sync

        now = time.monotonic()
        with self._lock:
            if self._cache is not None and (now - self._cache_time) < _CACHE_TTL:
                return self._cache

        # Run outside lock to avoid blocking concurrent readers
        results: list[DiscoveredRole] = discover_roles_sync(self.role_dirs)

        with self._lock:
            self._cache = results
            self._cache_time = time.monotonic()
        return results

    def find_path(self, role_id: str) -> Path | None:
        """Look up a role path by ID using cached discovery."""
        for d in self.discover():
            if role_path_to_id(d.path) == role_id:
                return d.path
        return None

    def invalidate(self) -> None:
        """Force next ``discover()`` to rescan."""
        with self._lock:
            self._cache = None
