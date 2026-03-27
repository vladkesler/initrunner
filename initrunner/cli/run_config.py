"""Run configuration: ~/.initrunner/run.yaml schema and loader."""

from __future__ import annotations

import logging
from pathlib import Path

from pydantic import BaseModel

from initrunner.config import get_home_dir

_logger = logging.getLogger(__name__)

_RUN_CONFIG_FILENAME = "run.yaml"
_LEGACY_CONFIG_FILENAME = "chat.yaml"


class RunConfig(BaseModel):
    """Configuration for ephemeral mode loaded from run.yaml."""

    provider: str | None = None
    model: str | None = None
    tool_profile: str = "minimal"
    tools: list[str] = []
    memory: bool = True
    ingest: list[str] = []
    personality: str | None = None
    name: str = "ephemeral"


def _get_run_config_path() -> Path:
    return get_home_dir() / _RUN_CONFIG_FILENAME


def load_run_config() -> RunConfig:
    """Load run config from ``~/.initrunner/run.yaml``.

    Falls back to ``chat.yaml`` with a migration warning if ``run.yaml``
    doesn't exist yet.  Returns defaults if neither file is present.
    """
    path = _get_run_config_path()
    legacy = get_home_dir() / _LEGACY_CONFIG_FILENAME

    if not path.is_file() and legacy.is_file():
        _logger.warning("Note: Rename %s to %s to preserve your settings.", legacy, path)
        # Print to stderr so it's visible even when stdout is piped
        import sys

        print(
            f"Note: Rename {legacy} to {path} to preserve your settings.",
            file=sys.stderr,
        )
        path = legacy

    if not path.is_file():
        return RunConfig()

    try:
        import yaml

        data = yaml.safe_load(path.read_text())
        if not isinstance(data, dict):
            return RunConfig()
        return RunConfig.model_validate(data)
    except Exception:
        _logger.warning("Failed to load %s, using defaults", path, exc_info=True)
        return RunConfig()


def resolve_ingest_paths(paths: list[str], config_dir: Path | None = None) -> list[str]:
    """Resolve relative ingest paths against the config directory.

    Absolute paths and URLs are returned as-is.
    Relative paths are resolved against *config_dir* (defaults to
    ``get_home_dir()``).
    """
    base = config_dir or get_home_dir()
    resolved: list[str] = []
    for p in paths:
        if p.startswith("http://") or p.startswith("https://"):
            resolved.append(p)
        elif not Path(p).is_absolute():
            resolved.append(str(base / p))
        else:
            resolved.append(p)
    return resolved
