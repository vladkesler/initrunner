"""Manifest persistence: load, save, and migrate registry.json."""

from __future__ import annotations

import json

from initrunner._paths import ensure_private_dir
from initrunner.config import get_roles_dir

ROLES_DIR = get_roles_dir()
MANIFEST_PATH = ROLES_DIR / "registry.json"


def _migrate_manifest_keys(data: dict) -> dict:
    """Migrate old bare-name keys to qualified install IDs on read."""
    roles = data.get("roles", {})
    migrated: dict[str, dict] = {}
    changed = False

    for key, entry in roles.items():
        if ":" in key:
            # Already qualified
            migrated[key] = entry
            continue

        # Legacy bare-name key -- assign a qualified ID
        source_type = entry.get("source_type", "github")
        if source_type == "oci":
            oci_ref = entry.get("oci_ref", "")
            qualified = f"oci:{oci_ref}/{key}" if oci_ref else f"oci:unknown/{key}"
        else:
            repo = entry.get("repo", "unknown")
            qualified = f"github:{repo}/{key}"

        # Store the display name in the entry
        entry.setdefault("display_name", key)
        migrated[qualified] = entry
        changed = True

    if changed:
        data["roles"] = migrated
    return data


def load_manifest() -> dict:
    """Read registry.json, return empty dict if missing. Migrates legacy keys."""
    if not MANIFEST_PATH.exists():
        return {"roles": {}}
    try:
        data = json.loads(MANIFEST_PATH.read_text())
        if "roles" not in data:
            data["roles"] = {}
        return _migrate_manifest_keys(data)
    except (json.JSONDecodeError, OSError):
        return {"roles": {}}


def save_manifest(data: dict) -> None:
    """Write registry.json atomically."""
    ensure_private_dir(ROLES_DIR)
    tmp = MANIFEST_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    tmp.replace(MANIFEST_PATH)
