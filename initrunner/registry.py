"""Role registry: install, uninstall, search, and manage community roles."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from initrunner.agent.schema.role import RoleDefinition

from initrunner._paths import ensure_private_dir
from initrunner.config import get_roles_dir

ROLES_DIR = get_roles_dir()
MANIFEST_PATH = ROLES_DIR / "registry.json"
INDEX_URL = "https://raw.githubusercontent.com/vladkesler/community-roles/main/index.yaml"

# Only allow downloads from GitHub raw content
_ALLOWED_HOST = "raw.githubusercontent.com"

_SOURCE_RE = re.compile(
    r"^(?P<owner>[A-Za-z0-9_.-]+)/(?P<repo>[A-Za-z0-9_.-]+)"
    r"(?::(?P<path>[^@]+))?"
    r"(?:@(?P<ref>.+))?$"
)


class RegistryError(Exception):
    """Base error for registry operations."""


class RoleExistsError(RegistryError):
    """Role is already installed."""


class RoleNotFoundError(RegistryError):
    """Role not found in registry or on GitHub."""


class NetworkError(RegistryError):
    """Network request failed."""


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class ResolvedSource:
    owner: str
    repo: str
    path: str
    ref: str
    raw_url: str

    @property
    def full_repo(self) -> str:
        return f"{self.owner}/{self.repo}"


@dataclass
class IndexEntry:
    name: str
    description: str
    author: str
    source: str
    tags: list[str] = field(default_factory=list)


@dataclass
class InstalledRole:
    name: str
    source: str
    repo: str
    ref: str
    local_path: Path
    installed_at: str
    source_type: str = "github"
    oci_ref: str = ""
    oci_digest: str = ""


@dataclass
class RoleInfo:
    name: str
    description: str
    author: str
    tools: list[str]
    model: str
    provider: str
    has_triggers: bool
    has_ingestion: bool
    has_memory: bool


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
    source_type: str  # "github", "oci", "hub"
    downloads: int = 0
    tools: list[str] = field(default_factory=list)
    model: str = ""
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Source identifier parsing
# ---------------------------------------------------------------------------


def resolve_source(identifier: str) -> ResolvedSource:
    """Resolve a source identifier to a structured format.

    Formats:
        user/repo                     → role.yaml in root, ref=main
        user/repo:path/to/role.yaml   → specific file, ref=main
        user/repo@v1.0                → role.yaml in root, pinned ref
        user/repo:path/role.yaml@v1.0 → specific file, pinned ref
        bare-name                     → lookup in community index
    """
    if "/" not in identifier:
        # Bare name — resolve via community index
        return _resolve_from_index(identifier)

    m = _SOURCE_RE.match(identifier)
    if m is None:
        raise RegistryError(f"Invalid source format: '{identifier}'")

    owner = m.group("owner")
    repo = m.group("repo")
    path = m.group("path") or "role.yaml"
    ref = m.group("ref") or "main"

    raw_url = f"https://{_ALLOWED_HOST}/{owner}/{repo}/{ref}/{path}"
    return ResolvedSource(owner=owner, repo=repo, path=path, ref=ref, raw_url=raw_url)


def _resolve_from_index(name: str) -> ResolvedSource:
    """Look up a bare role name in the community index."""
    entries = _fetch_index()
    for entry in entries:
        if entry.name == name:
            return resolve_source(entry.source)
    raise RoleNotFoundError(
        f"Role '{name}' not found in community index. "
        "Install directly with: initrunner install user/repo"
    )


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
# GitHub download + SHA fetch
# ---------------------------------------------------------------------------


def _build_request(url: str) -> urllib.request.Request:
    """Build a urllib Request with optional GitHub token."""
    req = urllib.request.Request(url)
    req.add_header("User-Agent", "initrunner-registry")
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        req.add_header("Authorization", f"token {token}")
    return req


def download_yaml(url: str) -> str:
    """Download raw YAML content from GitHub."""
    try:
        req = _build_request(url)
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise RoleNotFoundError(
                f"Role not found at {url}. Check the path and try again."
            ) from e
        if e.code == 403:
            raise NetworkError(
                "GitHub API rate limit reached. Set GITHUB_TOKEN env var for higher limits."
            ) from e
        raise NetworkError(f"HTTP {e.code} downloading {url}") from e
    except urllib.error.URLError as e:
        raise NetworkError("Could not reach GitHub. Check your connection.") from e


def fetch_commit_sha(repo: str, ref: str) -> str:
    """Get current commit SHA for a ref via GitHub API."""
    url = f"https://api.github.com/repos/{repo}/commits/{ref}"
    try:
        req = _build_request(url)
        req.add_header("Accept", "application/vnd.github.v3+json")
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data["sha"]
    except urllib.error.HTTPError as e:
        if e.code == 403:
            raise NetworkError(
                "GitHub API rate limit reached. Try again later, or set GITHUB_TOKEN."
            ) from e
        raise NetworkError(f"Could not fetch commit SHA for {repo}@{ref}: HTTP {e.code}") from e
    except (urllib.error.URLError, KeyError, json.JSONDecodeError) as e:
        raise NetworkError(f"Could not fetch commit SHA for {repo}@{ref}") from e


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _validate_yaml_content(content: str) -> RoleDefinition:
    """Validate YAML content as an InitRunner role. Returns RoleDefinition."""
    import yaml
    from pydantic import ValidationError

    from initrunner.agent.schema.role import RoleDefinition

    try:
        data = yaml.safe_load(content)
    except yaml.YAMLError as e:
        raise RegistryError(f"Downloaded file is not valid YAML: {e}") from e

    if not isinstance(data, dict):
        raise RegistryError(
            "Downloaded file is not a valid InitRunner role (expected YAML mapping)"
        )

    try:
        return RoleDefinition.model_validate(data)
    except ValidationError as e:
        raise RegistryError(f"Downloaded file is not a valid InitRunner role: {e}") from e


def check_dependencies(role: RoleDefinition) -> list[str]:
    """Check if role dependencies are satisfied. Returns warning strings."""
    import sys

    warnings: list[str] = []
    metadata = role.metadata

    for dep in metadata.dependencies:
        if dep.startswith("python"):
            # Simple version check: python>=3.11
            match = re.match(r"python>=(\d+\.\d+)", dep)
            if match:
                required = tuple(int(x) for x in match.group(1).split("."))
                current = sys.version_info[:2]
                if current < required:
                    warnings.append(
                        f"Requires Python >={match.group(1)}, you have {current[0]}.{current[1]}"
                    )
        else:
            if not shutil.which(dep):
                warnings.append(f"Dependency '{dep}' not found on PATH")

    return warnings


def _role_info_from_definition(role: RoleDefinition) -> RoleInfo:
    """Extract displayable info from a RoleDefinition."""
    return RoleInfo(
        name=role.metadata.name,
        description=role.metadata.description,
        author=role.metadata.author,
        tools=[t.type for t in role.spec.tools],
        model=role.spec.model.name,
        provider=role.spec.model.provider,
        has_triggers=bool(role.spec.triggers),
        has_ingestion=role.spec.ingest is not None,
        has_memory=role.spec.memory is not None,
    )


# ---------------------------------------------------------------------------
# Community index
# ---------------------------------------------------------------------------


def _fetch_index() -> list[IndexEntry]:
    """Fetch and parse the community role index."""
    import yaml

    try:
        content = download_yaml(INDEX_URL)
    except NetworkError:
        raise NetworkError(
            "Community index unavailable. Install directly: initrunner install user/repo"
        ) from None

    try:
        data = yaml.safe_load(content)
    except Exception as e:
        raise RegistryError(f"Invalid community index: {e}") from e

    if not isinstance(data, dict) or "roles" not in data:
        raise RegistryError("Invalid community index format")

    entries = []
    for item in data["roles"]:
        entries.append(
            IndexEntry(
                name=item["name"],
                description=item.get("description", ""),
                author=item.get("author", ""),
                source=item["source"],
                tags=item.get("tags", []),
            )
        )
    return entries


# ---------------------------------------------------------------------------
# Core operations
# ---------------------------------------------------------------------------


def preview_install(source: str, *, force: bool = False) -> InstallPreview:
    """Resolve source, fetch metadata, and return a preview. No file writes, no UI."""
    from initrunner.hub import is_hub_reference

    if is_hub_reference(source):
        return _preview_hub(source, force=force)

    from initrunner.packaging.oci import is_oci_reference

    if is_oci_reference(source):
        return _preview_oci(source, force=force)

    return _preview_github(source, force=force)


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
    from initrunner.hub import hub_resolve, parse_hub_reference

    owner, name, version = parse_hub_reference(source)
    info = hub_resolve(owner, name, version)

    resolved_version = version or info.latest_version
    if not resolved_version:
        raise RoleNotFoundError(f"No versions published for {owner}/{name}")

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


def _preview_github(source: str, *, force: bool = False) -> InstallPreview:
    """Resolve GitHub reference metadata into an InstallPreview."""
    resolved = resolve_source(source)
    content = download_yaml(resolved.raw_url)
    role = _validate_yaml_content(content)

    role_name = role.metadata.name
    safe_name = f"{resolved.owner}__{resolved.repo}__{role_name}.yaml"
    target = ROLES_DIR / safe_name

    if target.exists() and not force:
        raise RoleExistsError(f"Role '{role_name}' is already installed. Use --force to overwrite.")

    warnings = check_dependencies(role)
    info = _role_info_from_definition(role)

    return InstallPreview(
        name=info.name,
        description=info.description,
        author=info.author,
        version=resolved.ref,
        source_label=f"{resolved.full_repo}",
        source_type="github",
        tools=info.tools,
        model=f"{info.provider}/{info.model}",
        warnings=warnings,
    )


def confirm_install(source: str, *, force: bool = False) -> Path:
    """Actually install a role from any source. No UI output. Returns installed path."""
    from initrunner.hub import is_hub_reference

    if is_hub_reference(source):
        return _install_hub(source, force=force)

    from initrunner.packaging.oci import is_oci_reference

    if is_oci_reference(source):
        return _install_oci(source, force=force)

    return _install_github(source, force=force)


def _install_oci(oci_ref: str, *, force: bool = False) -> Path:
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

    manifest["roles"][qualified_key] = {
        "display_name": role_name,
        "source_type": "oci",
        "oci_ref": f"{ref.registry}/{ref.repository}",
        "oci_digest": oci_digest,
        "oci_tag": ref.tag,
        "local_path": target_dir.name,
        "installed_at": datetime.now(UTC).isoformat(),
    }
    save_manifest(manifest)
    return target_dir


def _install_hub(source: str, *, force: bool = False) -> Path:
    """Install a role from InitHub. No UI output."""
    import tempfile

    from initrunner.hub import hub_download, hub_resolve, parse_hub_reference
    from initrunner.packaging.bundle import extract_bundle

    owner, name, version = parse_hub_reference(source)
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
    manifest_data["roles"][qualified_key] = {
        "display_name": manifest.name,
        "source_type": "hub",
        "hub_owner": owner,
        "hub_name": name,
        "hub_version": resolved_version,
        "local_path": safe_name,
        "installed_at": datetime.now(UTC).isoformat(),
    }
    save_manifest(manifest_data)
    return target_dir


def _install_github(source: str, *, force: bool = False) -> Path:
    """Install a role from GitHub. No UI output."""
    resolved = resolve_source(source)
    content = download_yaml(resolved.raw_url)
    role = _validate_yaml_content(content)

    role_name = role.metadata.name
    safe_name = f"{resolved.owner}__{resolved.repo}__{role_name}.yaml"
    target = ROLES_DIR / safe_name

    if target.exists() and not force:
        raise RoleExistsError(f"Role '{role_name}' is already installed. Use --force to overwrite.")

    try:
        commit_sha = fetch_commit_sha(resolved.full_repo, resolved.ref)
    except NetworkError:
        commit_sha = ""

    ensure_private_dir(ROLES_DIR)
    target.write_text(content)

    manifest = load_manifest()
    qualified_key = f"github:{resolved.full_repo}/{role_name}"
    manifest["roles"][qualified_key] = {
        "display_name": role_name,
        "source_type": "github",
        "source_url": resolved.raw_url,
        "repo": resolved.full_repo,
        "path": resolved.path,
        "ref": resolved.ref,
        "commit_sha": commit_sha,
        "local_path": safe_name,
        "installed_at": datetime.now(UTC).isoformat(),
        "sha256": hashlib.sha256(content.encode()).hexdigest(),
    }
    save_manifest(manifest)
    return target


def install_role(source: str, *, force: bool = False, quiet: bool = False) -> Path:
    """Convenience: preview + install in one shot. No UI prompts.

    Use ``preview_install`` + ``confirm_install`` for interactive flows.
    """
    return confirm_install(source, force=force)


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
        results.append(
            InstalledRole(
                name=display_name,
                source=entry.get("source_url", entry.get("oci_ref", "")),
                repo=entry.get("repo", ""),
                ref=entry.get("ref", entry.get("oci_tag", "")),
                local_path=ROLES_DIR / entry["local_path"],
                installed_at=entry.get("installed_at", ""),
                source_type=source_type,
                oci_ref=entry.get("oci_ref", ""),
                oci_digest=entry.get("oci_digest", ""),
            )
        )
    return results


def info_role(source: str) -> RoleInfo | dict[str, Any]:
    """Download and parse role without installing. Return summary.

    For hub references, returns a dict with ``source_type: "hub"`` and package metadata.
    For OCI references, returns the bundle manifest metadata dict.
    For GitHub references, returns a ``RoleInfo`` dataclass.
    """
    from initrunner.hub import is_hub_reference

    if is_hub_reference(source):
        from initrunner.hub import hub_resolve, parse_hub_reference

        owner, name, _ = parse_hub_reference(source)
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

    from initrunner.packaging.oci import is_oci_reference

    if is_oci_reference(source):
        from initrunner.services.packaging import inspect_oci_role

        return inspect_oci_role(source)

    resolved = resolve_source(source)
    content = download_yaml(resolved.raw_url)
    role = _validate_yaml_content(content)
    return _role_info_from_definition(role)


def search_index(query: str) -> list[IndexEntry]:
    """Fetch community index, filter by name/description/tags."""
    entries = _fetch_index()
    query_lower = query.lower()
    results = []
    for entry in entries:
        if (
            query_lower in entry.name.lower()
            or query_lower in entry.description.lower()
            or any(query_lower in tag.lower() for tag in entry.tags)
        ):
            results.append(entry)
    return results


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

    old_sha = entry.get("commit_sha", "")
    repo = entry["repo"]
    ref = entry.get("ref", "main")

    # Warn if pinned to a tag
    if ref and not ref.startswith("v") and ref != "main" and len(ref) < 40:
        pass  # could be a branch
    elif ref and ref.startswith("v"):
        return UpdateResult(
            name=name,
            updated=False,
            old_sha=old_sha,
            new_sha=old_sha,
            message=f"Pinned to tag '{ref}' — tags are immutable. "
            "Reinstall with a different ref to update.",
        )

    try:
        new_sha = fetch_commit_sha(repo, ref)
    except NetworkError as e:
        return UpdateResult(
            name=name, updated=False, old_sha=old_sha, new_sha="", message=f"Error: {e}"
        )

    if new_sha == old_sha:
        return UpdateResult(
            name=name,
            updated=False,
            old_sha=old_sha,
            new_sha=new_sha,
            message="Already up to date.",
        )

    # Re-download
    source_url = entry["source_url"]
    try:
        content = download_yaml(source_url)
        _validate_yaml_content(content)
    except (NetworkError, RegistryError) as e:
        return UpdateResult(
            name=name, updated=False, old_sha=old_sha, new_sha=new_sha, message=f"Error: {e}"
        )

    local_path = ROLES_DIR / entry["local_path"]
    local_path.write_text(content)

    entry["commit_sha"] = new_sha
    entry["sha256"] = hashlib.sha256(content.encode()).hexdigest()
    entry["installed_at"] = datetime.now(UTC).isoformat()
    save_manifest(manifest)

    return UpdateResult(
        name=name, updated=True, old_sha=old_sha, new_sha=new_sha, message="Updated."
    )


def update_all() -> list[UpdateResult]:
    """Update all installed roles."""
    manifest = load_manifest()
    results = []
    for name in list(manifest["roles"]):
        results.append(update_role(name))
    return results


def hub_search_index(query: str) -> list[IndexEntry]:
    """Search InitHub for packages, return as IndexEntry for compatibility."""
    from initrunner.hub import hub_search

    results = hub_search(query)

    return [
        IndexEntry(
            name=f"{r.owner}/{r.name}",
            description=r.description,
            author=r.owner,
            source=f"hub:{r.owner}/{r.name}",
            tags=r.tags,
        )
        for r in results
    ]
