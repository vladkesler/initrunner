"""Business logic for OCI packaging operations."""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def publish_role(role_path: Path, oci_ref: str, *, tag: str | None = None) -> str:
    """Validate, bundle, and push a role to an OCI registry. Returns digest."""
    from initrunner.packaging.bundle import create_bundle, validate_bundle
    from initrunner.packaging.oci import OCIClient, parse_oci_ref

    ref = parse_oci_ref(oci_ref)
    if tag:
        ref.tag = tag

    # Create bundle
    from initrunner.config import get_bundles_cache_dir

    cache_dir = get_bundles_cache_dir()
    cache_dir.mkdir(parents=True, exist_ok=True)
    bundle_path = create_bundle(role_path, output_dir=cache_dir)

    # Validate bundle integrity
    manifest = validate_bundle(bundle_path)

    # Push to registry
    config_data = manifest.model_dump()
    client = OCIClient(ref)
    digest = client.push(bundle_path, config_data)

    # Cleanup cache
    try:
        bundle_path.unlink()
    except OSError:
        pass

    logger.info("Published %s to %s/%s:%s", manifest.name, ref.registry, ref.repository, ref.tag)
    return digest


def pull_role(oci_ref: str, *, force: bool = False) -> Path:
    """Pull an OCI artifact and install it locally. Returns extracted path."""
    from initrunner.packaging.oci import OCIClient, parse_oci_ref

    ref = parse_oci_ref(oci_ref)

    # Determine install directory
    from initrunner.config import get_roles_dir

    roles_dir = get_roles_dir()
    safe_name = f"oci__{ref.registry}__{ref.repository.replace('/', '__')}"
    target_dir = roles_dir / safe_name

    if target_dir.exists() and not force:
        from initrunner.registry import RoleExistsError

        raise RoleExistsError(
            f"OCI role already installed at {target_dir}. Use --force to overwrite."
        )

    if target_dir.exists():
        import shutil

        shutil.rmtree(target_dir)

    client = OCIClient(ref)
    client.pull(target_dir)

    return target_dir


def inspect_oci_role(oci_ref: str) -> dict:
    """Fetch config blob (manifest metadata) without downloading the full layer."""
    import json
    import urllib.error
    import urllib.request

    from initrunner.packaging.oci import (
        OCI_MANIFEST_MEDIA_TYPE,
        OCIClient,
        OCIError,
        parse_oci_ref,
    )

    ref = parse_oci_ref(oci_ref)
    client = OCIClient(ref)

    # Fetch the OCI manifest
    tag_or_digest = ref.digest or ref.tag
    url = f"{ref.api_prefix}/manifests/{tag_or_digest}"
    req = client._build_request(url)
    req.add_header("Accept", OCI_MANIFEST_MEDIA_TYPE)

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            manifest = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        raise OCIError(f"Failed to fetch manifest: HTTP {e.code}") from e

    # Fetch the config blob
    config_digest = manifest.get("config", {}).get("digest", "")
    if not config_digest:
        raise OCIError("No config digest in manifest")

    blob_url = f"{ref.api_prefix}/blobs/{config_digest}"
    req = client._build_request(blob_url)

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        raise OCIError(f"Failed to fetch config blob: HTTP {e.code}") from e
