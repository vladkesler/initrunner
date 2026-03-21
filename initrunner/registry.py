"""Role registry: install, uninstall, search, and manage community roles."""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from initrunner._paths import ensure_private_dir
from initrunner.config import get_roles_dir

ROLES_DIR = get_roles_dir()
MANIFEST_PATH = ROLES_DIR / "registry.json"


class RegistryError(Exception):
    """Base error for registry operations."""


class RoleExistsError(RegistryError):
    """Role is already installed."""


class RoleNotFoundError(RegistryError):
    """Role not found in registry or on GitHub."""


class NetworkError(RegistryError):
    """Network request failed."""


# ---------------------------------------------------------------------------
# Provider override helpers
# ---------------------------------------------------------------------------


def get_role_overrides(name: str) -> dict:
    """Return the ``overrides`` dict for an installed role, or ``{}``."""
    manifest = load_manifest()
    key = _find_manifest_key(manifest, name)
    if key is None:
        return {}
    return dict(manifest["roles"][key].get("overrides", {}))


def set_role_overrides(name: str, overrides: dict) -> None:
    """Store provider/model overrides for an installed role.

    Pass an empty dict to clear overrides.
    """
    manifest = load_manifest()
    key = _find_manifest_key(manifest, name)
    if key is None:
        raise RoleNotFoundError(f"Role '{name}' is not installed.")
    if overrides:
        manifest["roles"][key]["overrides"] = overrides
    else:
        manifest["roles"][key].pop("overrides", None)
    save_manifest(manifest)


def clear_role_overrides(name: str) -> None:
    """Remove provider/model overrides for an installed role."""
    set_role_overrides(name, {})


def get_overrides_for_path(role_path: Path) -> dict:
    """Return provider overrides for a role loaded by filesystem path, or ``{}``.

    Matches the path against installed roles by comparing the ``local_path``
    directory component.
    """
    manifest = load_manifest()
    try:
        role_dir = role_path.parent if role_path.is_file() else role_path
        rel = role_dir.relative_to(ROLES_DIR)
        top_dir = rel.parts[0] if rel.parts else ""
    except (ValueError, IndexError):
        return {}

    for _key, entry in manifest["roles"].items():
        if entry.get("local_path") == top_dir:
            return dict(entry.get("overrides", {}))
    return {}


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class InstallResult:
    """Result of a successful install."""

    path: Path
    display_name: str


@dataclass
class InstalledRole:
    name: str
    source: str
    repo: str
    ref: str
    local_path: Path
    installed_at: str
    source_type: str = "hub"
    oci_ref: str = ""
    oci_digest: str = ""
    hub_version: str = ""


@dataclass
class UpdateResult:
    name: str
    updated: bool
    old_sha: str
    new_sha: str
    message: str


@dataclass
class InstallPreview:
    """Metadata shown to user before confirming installation."""

    name: str
    description: str
    author: str
    version: str
    source_label: str
    source_type: str  # "oci" or "hub"
    downloads: int = 0
    tools: list[str] = field(default_factory=list)
    model: str = ""
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Manifest CRUD
# ---------------------------------------------------------------------------


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

        # Legacy bare-name key — assign a qualified ID
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


# ---------------------------------------------------------------------------
# Core operations
# ---------------------------------------------------------------------------


def preview_install(source: str, *, force: bool = False) -> InstallPreview:
    """Resolve source, fetch metadata, and return a preview. No file writes, no UI."""
    from initrunner.packaging.oci import is_oci_reference

    if is_oci_reference(source):
        return _preview_oci(source, force=force)

    # Bare name (no slash) -> error with search hint
    if "/" not in source:
        raise RegistryError(
            f"Unknown source '{source}'. Search InitHub: initrunner search {source}"
        )

    # Deprecated GitHub :path syntax
    if ":" in source and not source.startswith("hub:"):
        raise RegistryError(
            "GitHub ':path' syntax is no longer supported. "
            "Install from InitHub instead: initrunner install owner/name"
        )

    # Everything else: owner/name[@ver] or hub:owner/name[@ver] -> InitHub
    return _preview_hub(source, force=force)


def _preview_oci(oci_ref: str, *, force: bool = False) -> InstallPreview:
    """Resolve OCI reference metadata into an InstallPreview."""
    from initrunner.packaging.oci import parse_oci_ref
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
        description = bundle_meta.get("description", "")
        author = bundle_meta.get("author", "")
    else:
        role_name = "unknown"
        description = ""
        author = ""

    source_label = f"oci://{ref.registry}/{ref.repository}:{ref.tag}"
    return InstallPreview(
        name=role_name,
        description=description,
        author=author,
        version=ref.tag,
        source_label=source_label,
        source_type="oci",
    )


def _preview_hub(source: str, *, force: bool = False) -> InstallPreview:
    """Resolve hub reference metadata into an InstallPreview."""
    from initrunner.hub import hub_resolve, parse_hub_source

    owner, name, version = parse_hub_source(source)
    info = hub_resolve(owner, name, version)

    resolved_version = version or info.latest_version
    if not resolved_version:
        raise RoleNotFoundError(f"No versions published for {owner}/{name}")

    if version and info.versions and version not in info.versions:
        raise RoleNotFoundError(
            f"Version '{version}' not found for {owner}/{name}. "
            f"Available: {', '.join(info.versions)}"
        )

    # Check for existing install
    safe_name = f"hub__{owner}__{name}"
    target_dir = ROLES_DIR / safe_name
    if target_dir.exists() and not force:
        raise RoleExistsError(
            f"Role '{owner}/{name}' is already installed. Use --force to overwrite."
        )

    return InstallPreview(
        name=f"{owner}/{name}",
        description=info.description,
        author=info.author,
        version=resolved_version,
        source_label=f"hub:{owner}/{name}",
        source_type="hub",
        downloads=info.downloads,
    )


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
    manifest = load_manifest()

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
    save_manifest(manifest)
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
    target_dir = ROLES_DIR / safe_name

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
        ensure_private_dir(ROLES_DIR)
        manifest = extract_bundle(tmp_path, target_dir)
    finally:
        tmp_path.unlink(missing_ok=True)

    qualified_key = f"hub:{owner}/{name}"
    manifest_data = load_manifest()

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
    save_manifest(manifest_data)
    return InstallResult(path=target_dir, display_name=manifest.name)


def install_role(source: str, *, force: bool = False, quiet: bool = False) -> InstallResult:
    """Convenience: preview + install in one shot. No UI prompts.

    Use ``preview_install`` + ``confirm_install`` for interactive flows.
    """
    return confirm_install(source, force=force)


def resolve_installed_path(name: str) -> Path | None:
    """Resolve an installed role name to its directory.

    Raises RegistryError on ambiguous display name match.
    Returns None if no match found.
    """
    manifest = load_manifest()
    roles = manifest["roles"]

    # 1. Exact qualified key (e.g. "hub:alice/code-reviewer")
    if name in roles:
        p = ROLES_DIR / roles[name]["local_path"]
        if p.is_dir():
            return p

    # 2. owner/name -> hub:owner/name
    if "/" in name:
        hub_key = f"hub:{name}"
        if hub_key in roles:
            p = ROLES_DIR / roles[hub_key]["local_path"]
            if p.is_dir():
                return p

    # 3. Display name (must be unambiguous)
    matches = []
    for key, entry in roles.items():
        display = entry.get("display_name", key.rsplit("/", 1)[-1])
        if display == name:
            p = ROLES_DIR / entry["local_path"]
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


def uninstall_role(name: str) -> None:
    """Remove installed role file/directory + manifest entry."""
    manifest = load_manifest()

    key = _find_manifest_key(manifest, name)
    if key is None:
        raise RoleNotFoundError(f"Role '{name}' is not installed.")

    entry = manifest["roles"][key]
    local_path = ROLES_DIR / entry["local_path"]

    if local_path.exists():
        if local_path.is_dir():
            shutil.rmtree(local_path)
        else:
            local_path.unlink()

    del manifest["roles"][key]
    save_manifest(manifest)


def list_installed() -> list[InstalledRole]:
    """Read manifest, return installed roles with metadata."""
    manifest = load_manifest()
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
                local_path=ROLES_DIR / entry["local_path"],
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
    save_manifest(manifest)

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
    manifest = load_manifest()

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
    manifest = load_manifest()
    results = []
    for name in list(manifest["roles"]):
        results.append(update_role(name))
    return results
