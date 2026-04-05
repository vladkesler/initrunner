"""MCP tool schema cache -- persist ToolDefinitions to avoid connecting on startup."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic_ai.tools import ToolDefinition

from initrunner.agent._env import resolve_env_vars
from initrunner.agent.schema.tools import McpToolConfig
from initrunner.config import get_mcp_cache_dir

_logger = logging.getLogger(__name__)

CACHE_VERSION = 1


# ---------------------------------------------------------------------------
# Cached data model
# ---------------------------------------------------------------------------


@dataclass
class CachedTool:
    name: str
    description: str | None
    parameters_json_schema: dict[str, Any]
    metadata: dict[str, Any] | None


@dataclass
class CacheEntry:
    version: int
    cached_at: str
    tools: list[CachedTool]


# ---------------------------------------------------------------------------
# Cache key -- resolved transport identity
# ---------------------------------------------------------------------------


def cache_key(config: McpToolConfig, role_dir: Path | None) -> str:
    """Deterministic hash from resolved transport inputs.

    Unlike the Hub's ``_server_identity_hash`` (display-level, sorts args,
    ignores env values, uses raw cwd), this preserves arg order, hashes
    resolved env values, and resolves cwd against *role_dir* -- matching
    the behaviour of ``_transport.build_transport``.
    """
    parts: list[str] = [config.transport]

    if config.transport == "stdio":
        parts.append(config.command or "")
        parts.extend(config.args)  # order matters
        for k, v in sorted(config.env.items()):
            parts.append(f"{k}={resolve_env_vars(v)}")
        if config.cwd is not None:
            cwd = Path(config.cwd)
            if not cwd.is_absolute() and role_dir is not None:
                cwd = role_dir / cwd
            parts.append(str(cwd))
    else:
        parts.append(config.url or "")
        for k, v in sorted(config.headers.items()):
            parts.append(f"{k}={resolve_env_vars(v)}")

    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Read / write / invalidate
# ---------------------------------------------------------------------------


def _cache_path(key: str) -> Path:
    return get_mcp_cache_dir() / f"{key}.json"


def read_cache(key: str) -> CacheEntry | None:
    """Read a cache file.  Returns ``None`` on missing, corrupt, or wrong version."""
    path = _cache_path(key)
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text())
        if raw.get("version") != CACHE_VERSION:
            return None
        tools = [
            CachedTool(
                name=t["name"],
                description=t.get("description"),
                parameters_json_schema=t.get("parameters_json_schema", {}),
                metadata=t.get("metadata"),
            )
            for t in raw["tools"]
        ]
        return CacheEntry(version=raw["version"], cached_at=raw["cached_at"], tools=tools)
    except (json.JSONDecodeError, KeyError, TypeError):
        _logger.debug("Corrupt MCP cache file %s, ignoring", path)
        return None


def write_cache(key: str, tools: list[CachedTool]) -> None:
    """Atomic write: tmp file + rename."""
    directory = get_mcp_cache_dir()
    directory.mkdir(parents=True, exist_ok=True)

    entry = CacheEntry(
        version=CACHE_VERSION,
        cached_at=datetime.now(UTC).isoformat(),
        tools=tools,
    )
    data = json.dumps(asdict(entry), indent=2)

    fd, tmp = tempfile.mkstemp(dir=directory, suffix=".tmp")
    try:
        os.write(fd, data.encode())
        os.close(fd)
        os.replace(tmp, _cache_path(key))
    except BaseException:
        os.close(fd) if not os.get_inheritable(fd) else None  # pragma: no cover
        Path(tmp).unlink(missing_ok=True)
        raise


def invalidate_cache(key: str) -> bool:
    """Delete cache file.  Returns ``True`` if the file existed."""
    path = _cache_path(key)
    if path.exists():
        path.unlink()
        return True
    return False


def cache_age_seconds(key: str) -> float | None:
    """Seconds since ``cached_at``.  ``None`` if no cache."""
    entry = read_cache(key)
    if entry is None:
        return None
    try:
        cached_at = datetime.fromisoformat(entry.cached_at)
        return (datetime.now(UTC) - cached_at).total_seconds()
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Schema diff
# ---------------------------------------------------------------------------


def diff_schemas(cached: list[CachedTool], live: list[CachedTool]) -> list[str]:
    """Compare cached vs live tools.  Returns human-readable diff descriptions."""
    diffs: list[str] = []

    cached_map = {t.name: t for t in cached}
    live_map = {t.name: t for t in live}

    for name in sorted(live_map.keys() - cached_map.keys()):
        diffs.append(f"tool added: {name}")
    for name in sorted(cached_map.keys() - live_map.keys()):
        diffs.append(f"tool removed: {name}")
    for name in sorted(cached_map.keys() & live_map.keys()):
        old, new = cached_map[name], live_map[name]
        if old.parameters_json_schema != new.parameters_json_schema:
            diffs.append(f"tool changed (parameters): {name}")
        if old.description != new.description:
            diffs.append(f"tool changed (description): {name}")
        if old.metadata != new.metadata:
            diffs.append(f"tool changed (metadata): {name}")

    return diffs


# ---------------------------------------------------------------------------
# Conversion
# ---------------------------------------------------------------------------


def to_tool_definitions(entry: CacheEntry) -> list[ToolDefinition]:
    """Convert a ``CacheEntry`` to PydanticAI ``ToolDefinition`` objects."""
    return [
        ToolDefinition(
            name=t.name,
            description=t.description,
            parameters_json_schema=t.parameters_json_schema,
            metadata=t.metadata,
        )
        for t in entry.tools
    ]
