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
from typing import TYPE_CHECKING

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


def load_manifest() -> dict:
    """Read registry.json, return empty dict if missing."""
    if not MANIFEST_PATH.exists():
        return {"roles": {}}
    try:
        data = json.loads(MANIFEST_PATH.read_text())
        if "roles" not in data:
            data["roles"] = {}
        return data
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


def install_role(source: str, *, force: bool = False, yes: bool = False) -> Path:
    """Parse source -> download -> validate -> confirm -> save -> update manifest."""
    from rich.console import Console

    console = Console()

    # 1. Resolve source
    resolved = resolve_source(source)

    # 2. Download YAML
    console.print(f"Downloading from [cyan]{resolved.raw_url}[/cyan]...")
    content = download_yaml(resolved.raw_url)

    # 3. Validate as InitRunner role
    role = _validate_yaml_content(content)

    # 4. Compute namespaced filename
    role_name = role.metadata.name
    safe_name = f"{resolved.owner}__{resolved.repo}__{role_name}.yaml"
    target = ROLES_DIR / safe_name

    # 5. Collision check
    if target.exists() and not force:
        raise RoleExistsError(f"Role '{role_name}' is already installed. Use --force to overwrite.")

    # 6. Check dependencies and warn
    warnings = check_dependencies(role)
    for w in warnings:
        console.print(f"  [yellow]Warning:[/yellow] {w}")

    # 7. Security summary + confirmation
    info = _role_info_from_definition(role)
    if not yes:
        console.print()
        console.print(f"  [bold]Role:[/bold]        {info.name}")
        console.print(f"  [bold]Description:[/bold] {info.description or '(none)'}")
        console.print(f"  [bold]Author:[/bold]      {info.author or '(unknown)'}")
        tools_str = ", ".join(info.tools) if info.tools else "none"
        console.print(f"  [bold]Tools:[/bold]       {tools_str}")
        console.print(f"  [bold]Model:[/bold]       {info.provider}/{info.model}")
        if info.has_triggers:
            console.print("  [bold]Triggers:[/bold]    yes")
        if info.has_ingestion:
            console.print("  [bold]Ingestion:[/bold]   yes")
        if info.has_memory:
            console.print("  [bold]Memory:[/bold]      yes")
        console.print()

        import typer

        if not typer.confirm("Install this role?"):
            raise typer.Abort()

    # 8. Get commit SHA for tracking
    try:
        commit_sha = fetch_commit_sha(resolved.full_repo, resolved.ref)
    except NetworkError:
        commit_sha = ""

    # 9. Save file and update manifest
    ensure_private_dir(ROLES_DIR)
    target.write_text(content)

    manifest = load_manifest()
    manifest["roles"][role_name] = {
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

    console.print(f"[green]Installed[/green] {role_name} → {target}")
    return target


def uninstall_role(name: str) -> None:
    """Remove YAML file + manifest entry."""
    manifest = load_manifest()

    if name not in manifest["roles"]:
        raise RoleNotFoundError(f"Role '{name}' is not installed.")

    entry = manifest["roles"][name]
    local_path = ROLES_DIR / entry["local_path"]

    if local_path.exists():
        local_path.unlink()

    del manifest["roles"][name]
    save_manifest(manifest)


def list_installed() -> list[InstalledRole]:
    """Read manifest, return installed roles with metadata."""
    manifest = load_manifest()
    results = []
    for name, entry in manifest["roles"].items():
        results.append(
            InstalledRole(
                name=name,
                source=entry.get("source_url", ""),
                repo=entry.get("repo", ""),
                ref=entry.get("ref", "main"),
                local_path=ROLES_DIR / entry["local_path"],
                installed_at=entry.get("installed_at", ""),
            )
        )
    return results


def info_role(source: str) -> RoleInfo:
    """Download and parse role without installing. Return summary."""
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


def update_role(name: str) -> UpdateResult:
    """Compare remote SHA with stored SHA, re-download if changed."""
    manifest = load_manifest()

    if name not in manifest["roles"]:
        raise RoleNotFoundError(f"Role '{name}' is not installed.")

    entry = manifest["roles"][name]
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
