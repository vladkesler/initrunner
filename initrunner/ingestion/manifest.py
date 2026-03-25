"""Managed source manifest -- persisted in the document store's _meta table.

Dashboard-added files and URLs are tracked here so they survive re-ingestion
(not purged by ``_purge_deleted``) and survive store wipes (read before wipe,
written back after).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from initrunner.stores.base import DocumentStore


@dataclass
class ManagedSource:
    """A single entry in the managed source manifest."""

    path: str
    source_type: str  # "file" | "url"
    added_at: str  # ISO 8601


_META_KEY = "managed_sources"


# ---------------------------------------------------------------------------
# Read / write
# ---------------------------------------------------------------------------


def read_manifest_json(meta_value: str | None) -> list[ManagedSource]:
    """Parse a manifest JSON string into a list of :class:`ManagedSource`."""
    if not meta_value:
        return []
    try:
        raw = json.loads(meta_value)
    except (json.JSONDecodeError, TypeError):
        return []
    return [ManagedSource(**entry) for entry in raw if isinstance(entry, dict)]


def serialize_manifest(sources: list[ManagedSource]) -> str:
    """Serialize a manifest list to a JSON string."""
    return json.dumps([asdict(s) for s in sources], separators=(",", ":"))


def read_manifest(store: DocumentStore) -> list[ManagedSource]:
    """Read the managed source manifest from a :class:`DocumentStore`."""
    return read_manifest_json(store.read_store_meta(_META_KEY))


def write_manifest(store: DocumentStore, sources: list[ManagedSource]) -> None:
    """Write the managed source manifest to a :class:`DocumentStore`."""
    store.write_store_meta(_META_KEY, serialize_manifest(sources))


# ---------------------------------------------------------------------------
# Mutators
# ---------------------------------------------------------------------------


def add_to_manifest(
    store: DocumentStore,
    entries: list[ManagedSource],
) -> list[ManagedSource]:
    """Add entries to the manifest, deduplicating by path. Returns the new list."""
    existing = read_manifest(store)
    existing_paths = {s.path for s in existing}
    for entry in entries:
        if entry.path not in existing_paths:
            existing.append(entry)
            existing_paths.add(entry.path)
    write_manifest(store, existing)
    return existing


def remove_from_manifest(
    store: DocumentStore,
    path: str,
) -> list[ManagedSource]:
    """Remove an entry by path. Returns the new list."""
    existing = read_manifest(store)
    updated = [s for s in existing if s.path != path]
    if len(updated) != len(existing):
        write_manifest(store, updated)
    return updated


# ---------------------------------------------------------------------------
# Upload directory
# ---------------------------------------------------------------------------


def uploads_dir(agent_name: str) -> Path:
    """Return ``~/.initrunner/uploads/{agent_name}/``, creating it if needed."""
    from initrunner._paths import ensure_private_dir
    from initrunner.config import get_home_dir

    d = get_home_dir() / "uploads" / agent_name
    ensure_private_dir(d)
    return d
