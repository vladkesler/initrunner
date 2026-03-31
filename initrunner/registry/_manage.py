"""Role lifecycle: uninstall, list, inspect."""

from __future__ import annotations

import shutil
from typing import Any

from initrunner.registry import _manifest
from initrunner.registry._exceptions import RegistryError, RoleNotFoundError
from initrunner.registry._resolve import _find_manifest_key
from initrunner.registry._types import InstalledRole


def uninstall_role(name: str) -> None:
    """Remove installed role file/directory + manifest entry."""
    manifest = _manifest.load_manifest()

    key = _find_manifest_key(manifest, name)
    if key is None:
        raise RoleNotFoundError(f"Role '{name}' is not installed.")

    entry = manifest["roles"][key]
    local_path = _manifest.ROLES_DIR / entry["local_path"]

    if local_path.exists():
        if local_path.is_dir():
            shutil.rmtree(local_path)
        else:
            local_path.unlink()

    del manifest["roles"][key]
    _manifest.save_manifest(manifest)


def list_installed() -> list[InstalledRole]:
    """Read manifest, return installed roles with metadata."""
    manifest = _manifest.load_manifest()
    results = []
    for key, entry in manifest["roles"].items():
        display_name = entry.get("display_name", key.rsplit("/", 1)[-1])
        source_type = entry.get("source_type", "github")
        repo = entry.get("repo", "")
        ref = entry.get("ref", entry.get("oci_tag", ""))
        if source_type == "hub":
            repo = f"{entry.get('hub_owner', '')}/{entry.get('hub_name', '')}"
            ref = entry.get("hub_version", "")
        results.append(
            InstalledRole(
                name=display_name,
                source=entry.get("source_url", entry.get("oci_ref", "")),
                repo=repo,
                ref=ref,
                local_path=_manifest.ROLES_DIR / entry["local_path"],
                installed_at=entry.get("installed_at", ""),
                source_type=source_type,
                oci_ref=entry.get("oci_ref", ""),
                oci_digest=entry.get("oci_digest", ""),
                hub_version=entry.get("hub_version", ""),
            )
        )
    return results


def info_role(source: str) -> dict[str, Any]:
    """Inspect a role without installing. Returns metadata dict.

    For hub references, returns package metadata from InitHub.
    For OCI references, returns the bundle manifest metadata dict.
    """
    from initrunner.packaging.oci import is_oci_reference

    if is_oci_reference(source):
        from initrunner.services.packaging import inspect_oci_role

        return inspect_oci_role(source)

    if "/" not in source:
        raise RegistryError(
            f"Unknown source '{source}'. Search InitHub: initrunner search {source}"
        )

    if ":" in source and not source.startswith("hub:"):
        raise RegistryError(
            "GitHub ':path' syntax is no longer supported. "
            "Use InitHub instead: initrunner info owner/name"
        )

    from initrunner.hub import hub_resolve, parse_hub_source

    owner, name, _ = parse_hub_source(source)
    pkg = hub_resolve(owner, name)
    return {
        "name": f"{pkg.owner}/{pkg.name}",
        "description": pkg.description,
        "author": pkg.author,
        "latest_version": pkg.latest_version,
        "downloads": pkg.downloads,
        "tags": pkg.tags,
        "versions": pkg.versions,
        "repository_url": pkg.repository_url,
        "source_type": "hub",
    }
