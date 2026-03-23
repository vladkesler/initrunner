"""Dashboard configuration -- composes existing InitRunner config helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class DashboardSettings:
    """Settings for the dashboard server.

    Role dirs and audit DB path are composed from existing InitRunner
    config (``initrunner.config`` / ``initrunner.services.discovery``)
    rather than redefined here.
    """

    port: int = 8100
    expose: bool = False
    extra_role_dirs: list[Path] = field(default_factory=list)

    @property
    def host(self) -> str:
        return "0.0.0.0" if self.expose else "127.0.0.1"

    def get_role_dirs(self) -> list[Path]:
        from initrunner.services.discovery import get_default_role_dirs

        dirs = get_default_role_dirs()
        for d in self.extra_role_dirs:
            if d not in dirs:
                dirs.append(d)
        return dirs

    def get_audit_db(self) -> Path:
        from initrunner.config import get_audit_db_path

        return get_audit_db_path()
