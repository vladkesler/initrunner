"""Provider/model override persistence for installed roles."""

from __future__ import annotations

from pathlib import Path

from initrunner.registry import _manifest
from initrunner.registry._exceptions import RoleNotFoundError
from initrunner.registry._resolve import _find_manifest_key


def get_role_overrides(name: str) -> dict:
    """Return the ``overrides`` dict for an installed role, or ``{}``."""
    manifest = _manifest.load_manifest()
    key = _find_manifest_key(manifest, name)
    if key is None:
        return {}
    return dict(manifest["roles"][key].get("overrides", {}))


def set_role_overrides(name: str, overrides: dict) -> None:
    """Store provider/model overrides for an installed role.

    Pass an empty dict to clear overrides.
    """
    manifest = _manifest.load_manifest()
    key = _find_manifest_key(manifest, name)
    if key is None:
        raise RoleNotFoundError(f"Role '{name}' is not installed.")
    if overrides:
        manifest["roles"][key]["overrides"] = overrides
    else:
        manifest["roles"][key].pop("overrides", None)
    _manifest.save_manifest(manifest)


def clear_role_overrides(name: str) -> None:
    """Remove provider/model overrides for an installed role."""
    set_role_overrides(name, {})


def get_overrides_for_path(role_path: Path) -> dict:
    """Return provider overrides for a role loaded by filesystem path, or ``{}``.

    Matches the path against installed roles by comparing the ``local_path``
    directory component.
    """
    manifest = _manifest.load_manifest()
    try:
        role_dir = role_path.parent if role_path.is_file() else role_path
        rel = role_dir.relative_to(_manifest.ROLES_DIR)
        top_dir = rel.parts[0] if rel.parts else ""
    except (ValueError, IndexError):
        return {}

    for _key, entry in manifest["roles"].items():
        if entry.get("local_path") == top_dir:
            return dict(entry.get("overrides", {}))
    return {}
