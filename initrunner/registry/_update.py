"""Role update: check remote for newer versions and re-download."""

from __future__ import annotations

from datetime import UTC, datetime

from initrunner.registry import _manifest
from initrunner.registry._exceptions import RoleNotFoundError
from initrunner.registry._install import _install_hub
from initrunner.registry._resolve import _find_manifest_key
from initrunner.registry._types import UpdateResult


def _update_oci_role(key: str, entry: dict, manifest: dict) -> UpdateResult:
    """Update an OCI-installed role by checking for new digest."""
    display_name = entry.get("display_name", key.rsplit("/", 1)[-1])
    old_digest = entry.get("oci_digest", "")
    oci_ref_str = entry.get("oci_ref", "")
    oci_tag = entry.get("oci_tag", "latest")

    if not oci_ref_str:
        return UpdateResult(
            name=display_name,
            updated=False,
            old_sha=old_digest,
            new_sha="",
            message="No OCI reference stored.",
        )

    from initrunner.packaging.oci import OCIClient, OCIError, OCIRef, _is_localhost

    # Parse stored ref
    parts = oci_ref_str.split("/", 1)
    if len(parts) < 2:
        return UpdateResult(
            name=display_name,
            updated=False,
            old_sha=old_digest,
            new_sha="",
            message=f"Invalid stored OCI ref: {oci_ref_str}",
        )

    ref = OCIRef(
        registry=parts[0],
        repository=parts[1],
        tag=oci_tag,
        insecure=_is_localhost(parts[0]),
    )

    try:
        client = OCIClient(ref)
        head_info = client.head()
        new_digest = head_info.get("digest", "")
    except OCIError as e:
        return UpdateResult(
            name=display_name,
            updated=False,
            old_sha=old_digest,
            new_sha="",
            message=f"Error: {e}",
        )

    if new_digest == old_digest:
        return UpdateResult(
            name=display_name,
            updated=False,
            old_sha=old_digest,
            new_sha=new_digest,
            message="Already up to date.",
        )

    # Re-pull
    full_ref = f"oci://{oci_ref_str}:{oci_tag}"
    try:
        from initrunner.services.packaging import pull_role

        pull_role(full_ref, force=True)
    except Exception as e:
        return UpdateResult(
            name=display_name,
            updated=False,
            old_sha=old_digest,
            new_sha=new_digest,
            message=f"Error: {e}",
        )

    entry["oci_digest"] = new_digest
    entry["installed_at"] = datetime.now(UTC).isoformat()
    _manifest.save_manifest(manifest)

    return UpdateResult(
        name=display_name,
        updated=True,
        old_sha=old_digest,
        new_sha=new_digest,
        message="Updated.",
    )


def _update_hub_role(key: str, entry: dict, manifest: dict) -> UpdateResult:
    """Update a hub-installed role by checking for new version."""
    display_name = entry.get("display_name", key.rsplit("/", 1)[-1])
    owner = entry.get("hub_owner", "")
    name = entry.get("hub_name", "")
    old_version = entry.get("hub_version", "")

    if not owner or not name:
        return UpdateResult(
            name=display_name,
            updated=False,
            old_sha=old_version,
            new_sha="",
            message="No hub reference stored.",
        )

    from initrunner.hub import HubError, hub_resolve

    try:
        info = hub_resolve(owner, name)
    except HubError as e:
        return UpdateResult(
            name=display_name,
            updated=False,
            old_sha=old_version,
            new_sha="",
            message=f"Error: {e}",
        )

    new_version = info.latest_version
    if not new_version or new_version == old_version:
        return UpdateResult(
            name=display_name,
            updated=False,
            old_sha=old_version,
            new_sha=new_version or "",
            message="Already up to date.",
        )

    # Re-install
    try:
        _install_hub(f"hub:{owner}/{name}@{new_version}", force=True)
    except Exception as e:
        return UpdateResult(
            name=display_name,
            updated=False,
            old_sha=old_version,
            new_sha=new_version,
            message=f"Error: {e}",
        )

    return UpdateResult(
        name=display_name,
        updated=True,
        old_sha=old_version,
        new_sha=new_version,
        message=f"Updated to {new_version}.",
    )


def update_role(name: str) -> UpdateResult:
    """Compare remote SHA with stored SHA, re-download if changed."""
    manifest = _manifest.load_manifest()

    key = _find_manifest_key(manifest, name)
    if key is None:
        raise RoleNotFoundError(f"Role '{name}' is not installed.")

    entry = manifest["roles"][key]

    # Handle OCI sources
    if entry.get("source_type") == "oci":
        return _update_oci_role(key, entry, manifest)

    # Handle hub sources
    if entry.get("source_type") == "hub":
        return _update_hub_role(key, entry, manifest)

    # Legacy GitHub source -- no longer supported
    display_name = entry.get("display_name", key.rsplit("/", 1)[-1])
    return UpdateResult(
        name=display_name,
        updated=False,
        old_sha="",
        new_sha="",
        message="Installed from GitHub (no longer supported). "
        "Reinstall from InitHub: initrunner install owner/name",
    )


def update_all() -> list[UpdateResult]:
    """Update all installed roles."""
    manifest = _manifest.load_manifest()
    results = []
    for name in list(manifest["roles"]):
        results.append(update_role(name))
    return results
