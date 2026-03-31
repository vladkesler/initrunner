"""Role installation from OCI and InitHub sources."""

from __future__ import annotations

import shutil
from datetime import UTC, datetime
from pathlib import Path

from initrunner._paths import ensure_private_dir
from initrunner.registry import _manifest
from initrunner.registry._exceptions import (
    RegistryError,
    RoleExistsError,
    RoleNotFoundError,
)
from initrunner.registry._types import InstallResult


def confirm_install(source: str, *, force: bool = False) -> InstallResult:
    """Actually install a role from any source. No UI output. Returns InstallResult."""
    from initrunner.packaging.oci import is_oci_reference

    if is_oci_reference(source):
        return _install_oci(source, force=force)

    if "/" not in source:
        raise RegistryError(
            f"Unknown source '{source}'. Search InitHub: initrunner search {source}"
        )

    if ":" in source and not source.startswith("hub:"):
        raise RegistryError(
            "GitHub ':path' syntax is no longer supported. "
            "Install from InitHub instead: initrunner install owner/name"
        )

    return _install_hub(source, force=force)


def _install_oci(oci_ref: str, *, force: bool = False) -> InstallResult:
    """Pull an OCI bundle and install it locally."""
    from initrunner.packaging.oci import OCIClient, OCIError, parse_oci_ref
    from initrunner.services.packaging import pull_role

    ref = parse_oci_ref(oci_ref)

    try:
        target_dir = pull_role(oci_ref, force=force)
    except RoleExistsError:
        if not force:
            raise
        target_dir = pull_role(oci_ref, force=True)

    # Read manifest.json from extracted bundle
    manifest_json = target_dir / "manifest.json"
    if manifest_json.exists():
        import json as _json

        bundle_meta = _json.loads(manifest_json.read_text())
        role_name = bundle_meta.get("name", "unknown")
    else:
        role_name = "unknown"

    # Get digest for tracking
    try:
        client = OCIClient(ref)
        head_info = client.head()
        oci_digest = head_info.get("digest", "")
    except OCIError:
        oci_digest = ""

    # Update manifest with qualified key
    qualified_key = f"oci:{ref.registry}/{ref.repository}/{role_name}"
    manifest = _manifest.load_manifest()

    # Check for display name collision from different source
    for key, entry in manifest["roles"].items():
        entry_name = entry.get("display_name", key.rsplit("/", 1)[-1])
        if entry_name == role_name and key != qualified_key and not force:
            shutil.rmtree(target_dir, ignore_errors=True)
            raise RoleExistsError(f"Name collision: '{role_name}' already installed from {key}")

    # Preserve user's provider overrides across reinstall/update
    existing_overrides = {}
    if qualified_key in manifest["roles"]:
        existing_overrides = manifest["roles"][qualified_key].get("overrides", {})

    new_entry: dict = {
        "display_name": role_name,
        "source_type": "oci",
        "oci_ref": f"{ref.registry}/{ref.repository}",
        "oci_digest": oci_digest,
        "oci_tag": ref.tag,
        "local_path": target_dir.name,
        "installed_at": datetime.now(UTC).isoformat(),
    }
    if existing_overrides:
        new_entry["overrides"] = existing_overrides

    manifest["roles"][qualified_key] = new_entry
    _manifest.save_manifest(manifest)
    return InstallResult(path=target_dir, display_name=role_name)


def _install_hub(source: str, *, force: bool = False) -> InstallResult:
    """Install a role from InitHub. No UI output."""
    import tempfile

    from initrunner.hub import hub_download, hub_resolve, parse_hub_source
    from initrunner.packaging.bundle import extract_bundle

    owner, name, version = parse_hub_source(source)
    info = hub_resolve(owner, name, version)

    resolved_version = version or info.latest_version
    if not resolved_version:
        raise RoleNotFoundError(f"No versions published for {owner}/{name}")

    safe_name = f"hub__{owner}__{name}"
    target_dir = _manifest.ROLES_DIR / safe_name

    if target_dir.exists() and not force:
        raise RoleExistsError(
            f"Role '{owner}/{name}' is already installed. Use --force to overwrite."
        )

    bundle_data = hub_download(owner, name, resolved_version)

    with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as tmp:
        tmp.write(bundle_data)
        tmp_path = Path(tmp.name)

    try:
        if target_dir.exists():
            shutil.rmtree(target_dir)
        ensure_private_dir(_manifest.ROLES_DIR)
        manifest = extract_bundle(tmp_path, target_dir)
    finally:
        tmp_path.unlink(missing_ok=True)

    qualified_key = f"hub:{owner}/{name}"
    manifest_data = _manifest.load_manifest()

    # Preserve user's provider overrides across reinstall/update
    existing_overrides = {}
    if qualified_key in manifest_data["roles"]:
        existing_overrides = manifest_data["roles"][qualified_key].get("overrides", {})

    new_entry: dict = {
        "display_name": manifest.name,
        "source_type": "hub",
        "hub_owner": owner,
        "hub_name": name,
        "hub_version": resolved_version,
        "local_path": safe_name,
        "installed_at": datetime.now(UTC).isoformat(),
    }
    if existing_overrides:
        new_entry["overrides"] = existing_overrides

    manifest_data["roles"][qualified_key] = new_entry
    _manifest.save_manifest(manifest_data)
    return InstallResult(path=target_dir, display_name=manifest.name)


def install_role(source: str, *, force: bool = False, quiet: bool = False) -> InstallResult:
    """Convenience: preview + install in one shot. No UI prompts.

    Use ``preview_install`` + ``confirm_install`` for interactive flows.
    """
    return confirm_install(source, force=force)
