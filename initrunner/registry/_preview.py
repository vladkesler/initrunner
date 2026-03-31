"""Preview (dry-run) installation from OCI or InitHub sources."""

from __future__ import annotations

from initrunner.registry import _manifest
from initrunner.registry._exceptions import (
    RegistryError,
    RoleExistsError,
    RoleNotFoundError,
)
from initrunner.registry._types import InstallPreview


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
    target_dir = _manifest.ROLES_DIR / safe_name
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
