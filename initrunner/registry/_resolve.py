"""Installed-role resolution and lookup."""

from __future__ import annotations

from pathlib import Path

from initrunner.registry import _manifest
from initrunner.registry._exceptions import RegistryError


def resolve_installed_path(name: str) -> Path | None:
    """Resolve an installed role name to its directory.

    Raises RegistryError on ambiguous display name match.
    Returns None if no match found.
    """
    manifest = _manifest.load_manifest()
    roles = manifest["roles"]

    # 1. Exact qualified key (e.g. "hub:alice/code-reviewer")
    if name in roles:
        p = _manifest.ROLES_DIR / roles[name]["local_path"]
        if p.is_dir():
            return p

    # 2. owner/name -> hub:owner/name
    if "/" in name:
        hub_key = f"hub:{name}"
        if hub_key in roles:
            p = _manifest.ROLES_DIR / roles[hub_key]["local_path"]
            if p.is_dir():
                return p

    # 3. Display name (must be unambiguous)
    matches = []
    for key, entry in roles.items():
        display = entry.get("display_name", key.rsplit("/", 1)[-1])
        if display == name:
            p = _manifest.ROLES_DIR / entry["local_path"]
            if p.is_dir():
                matches.append((key, p))

    if len(matches) == 1:
        return matches[0][1]
    if len(matches) > 1:
        sources = ", ".join(k for k, _ in matches)
        raise RegistryError(
            f"Ambiguous role name '{name}' -- installed from: {sources}. "
            f"Use the qualified name instead."
        )
    return None


def _find_manifest_key(manifest: dict, name: str) -> str | None:
    """Find a manifest key by qualified ID or display name."""
    # Exact match first
    if name in manifest["roles"]:
        return name

    # Search by display name
    for key, entry in manifest["roles"].items():
        display = entry.get("display_name", key.rsplit("/", 1)[-1])
        if display == name:
            return key

    return None
