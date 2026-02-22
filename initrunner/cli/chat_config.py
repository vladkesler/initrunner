"""Chat configuration: ~/.initrunner/chat.yaml schema and loader."""

from __future__ import annotations

import logging
from pathlib import Path

from pydantic import BaseModel

from initrunner.config import get_home_dir

_logger = logging.getLogger(__name__)

_CHAT_CONFIG_FILENAME = "chat.yaml"


class ChatConfig(BaseModel):
    """Configuration for ``initrunner chat`` loaded from chat.yaml."""

    provider: str | None = None
    model: str | None = None
    tool_profile: str = "minimal"
    tools: list[str] = []
    memory: bool = True
    ingest: list[str] = []
    personality: str | None = None
    name: str = "ephemeral-chat"


def _get_chat_config_path() -> Path:
    return get_home_dir() / _CHAT_CONFIG_FILENAME


def load_chat_config() -> ChatConfig:
    """Load chat config from ``~/.initrunner/chat.yaml``.

    Returns defaults if the file is missing or unparseable.
    """
    path = _get_chat_config_path()
    if not path.is_file():
        return ChatConfig()

    try:
        import yaml

        data = yaml.safe_load(path.read_text())
        if not isinstance(data, dict):
            return ChatConfig()
        return ChatConfig.model_validate(data)
    except Exception:
        _logger.warning("Failed to load %s, using defaults", path, exc_info=True)
        return ChatConfig()


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
