"""InitHub marketplace API client."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from initrunner.config import get_hub_auth_path
from initrunner.registry import RegistryError

INITHUB_API_URL = os.environ.get("INITHUB_API_URL", "https://api.hub.initrunner.ai/api/v1")


@dataclass
class HubSearchResult:
    owner: str
    name: str
    description: str
    tags: list[str] = field(default_factory=list)
    downloads: int = 0
    latest_version: str = ""


@dataclass
class HubPackageInfo:
    owner: str
    name: str
    description: str
    tags: list[str] = field(default_factory=list)
    latest_version: str = ""
    versions: list[str] = field(default_factory=list)
    downloads: int = 0
    author: str = ""
    repository_url: str = ""
    created_at: str = ""


class HubError(RegistryError):
    """Error communicating with InitHub."""


class HubAuthError(HubError):
    """Authentication failed."""


class HubDeviceCodeExpired(HubError):
    """Device code has expired."""


def save_hub_token(token: str) -> None:
    """Save InitHub API token to disk."""
    from initrunner._paths import ensure_private_dir

    path = get_hub_auth_path()
    ensure_private_dir(path.parent)
    path.write_text(json.dumps({"token": token}))
    path.chmod(0o600)


def load_hub_token() -> str | None:
    """Load stored InitHub API token."""
    path = get_hub_auth_path()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        return data.get("token")
    except (json.JSONDecodeError, OSError):
        return None


def remove_hub_token() -> None:
    """Remove stored InitHub API token."""
    path = get_hub_auth_path()
    if path.exists():
        path.unlink()


def _hub_request(
    path: str,
    *,
    method: str = "GET",
    token: str | None = None,
    data: bytes | None = None,
    headers: dict[str, str] | None = None,
    content_type: str | None = None,
) -> dict:
    """Make an HTTP request to InitHub API."""
    url = f"{INITHUB_API_URL}{path}"
    req = urllib.request.Request(url, method=method)
    req.add_header("User-Agent", "initrunner-hub-client")

    if token:
        req.add_header("Authorization", f"Bearer {token}")

    if headers:
        for k, v in headers.items():
            req.add_header(k, v)

    if content_type:
        req.add_header("Content-Type", content_type)

    try:
        with urllib.request.urlopen(req, data=data, timeout=60) as resp:
            body = resp.read()
            if not body:
                return {}
            return json.loads(body)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        if e.code == 401:
            raise HubAuthError(
                "Authentication failed. Run 'initrunner login' to authenticate."
            ) from e
        if e.code == 404:
            raise HubError(f"Not found: {path}") from e
        raise HubError(f"InitHub API error (HTTP {e.code}): {body}") from e
    except urllib.error.URLError as e:
        raise HubError("Could not reach InitHub. Check your connection.") from e


def hub_search(query: str, tags: list[str] | None = None) -> list[HubSearchResult]:
    """Search InitHub for packages."""
    params = f"?q={urllib.parse.quote(query)}"
    if tags:
        for tag in tags:
            params += f"&tag={urllib.parse.quote(tag)}"

    data = _hub_request(f"/packages{params}")
    results = []
    for item in data.get("items", []):
        owner_data = item.get("owner", {})
        latest = item.get("latest_version")
        results.append(
            HubSearchResult(
                owner=owner_data.get("username", ""),
                name=item.get("slug", ""),
                description=item.get("description", ""),
                tags=latest.get("tags", []) if latest else [],
                downloads=item.get("downloads_total", 0),
                latest_version=latest.get("version", "") if latest else "",
            )
        )
    return results


def hub_browse(limit: int = 12) -> list[HubSearchResult]:
    """Fetch popular packages from InitHub (no search query required)."""
    params = f"?limit={limit}&sort=downloads"
    data = _hub_request(f"/packages{params}")
    results = []
    for item in data.get("items", []):
        owner_data = item.get("owner", {})
        latest = item.get("latest_version")
        results.append(
            HubSearchResult(
                owner=owner_data.get("username", ""),
                name=item.get("slug", ""),
                description=item.get("description", ""),
                tags=latest.get("tags", []) if latest else [],
                downloads=item.get("downloads_total", 0),
                latest_version=latest.get("version", "") if latest else "",
            )
        )
    return results


def hub_resolve(owner: str, name: str, version: str | None = None) -> HubPackageInfo:
    """Get package metadata from InitHub."""
    data = _hub_request(f"/packages/{owner}/{name}")
    versions_data = _hub_request(f"/packages/{owner}/{name}/versions")

    latest = data.get("latest_version")
    return HubPackageInfo(
        owner=owner,
        name=data.get("slug", name),
        description=data.get("description", ""),
        tags=latest.get("tags", []) if latest else [],
        latest_version=latest.get("version", "") if latest else "",
        versions=[v["version"] for v in versions_data],
        downloads=data.get("downloads_total", 0),
        author=latest.get("author", "") if latest else "",
        repository_url=data.get("repository_url", ""),
        created_at=data.get("created_at", ""),
    )


def hub_download(owner: str, name: str, version: str | None = None) -> bytes:
    """Download a bundle .tar.gz from InitHub."""
    if version:
        url = f"{INITHUB_API_URL}/packages/{owner}/{name}/versions/{version}/download"
    else:
        # Resolve latest version first
        info = hub_resolve(owner, name)
        if not info.latest_version:
            raise HubError(f"No versions published for {owner}/{name}")
        url = f"{INITHUB_API_URL}/packages/{owner}/{name}/versions/{info.latest_version}/download"

    req = urllib.request.Request(url)
    req.add_header("User-Agent", "initrunner-hub-client")

    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return resp.read()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise HubError(f"Package not found: {owner}/{name}") from e
        raise HubError(f"Download failed (HTTP {e.code})") from e
    except urllib.error.URLError as e:
        raise HubError("Could not reach InitHub. Check your connection.") from e


def hub_publish(
    bundle_path: str,
    token: str,
    *,
    readme: str | None = None,
    repository_url: str | None = None,
    categories: list[str] | None = None,
) -> dict:
    """Publish a bundle to InitHub."""
    import mimetypes
    import uuid

    boundary = uuid.uuid4().hex
    parts: list[bytes] = []

    # Bundle file part
    bundle_data = Path(bundle_path).read_bytes()
    filename = Path(bundle_path).name
    mime = mimetypes.guess_type(filename)[0] or "application/gzip"
    parts.append(
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="bundle"; filename="{filename}"\r\n'
        f"Content-Type: {mime}\r\n\r\n".encode()
    )
    parts.append(bundle_data)
    parts.append(b"\r\n")

    parts.append(f"--{boundary}--\r\n".encode())

    body = b"".join(parts)

    # The InitHub API expects readme, repository_url, and categories as
    # query parameters, not multipart form fields.
    query_params: dict[str, str] = {}
    if readme:
        query_params["readme"] = readme
    if repository_url:
        query_params["repository_url"] = repository_url
    if categories:
        query_params["categories"] = json.dumps(categories)

    query_string = urllib.parse.urlencode(query_params) if query_params else ""
    path = f"/packages?{query_string}" if query_string else "/packages"

    return _hub_request(
        path,
        method="POST",
        token=token,
        data=body,
        content_type=f"multipart/form-data; boundary={boundary}",
    )


def request_device_code() -> dict:
    """Request a new device code for CLI login.

    Returns dict with device_code, user_code, verification_url, interval_seconds, expires_at.
    """
    url = f"{INITHUB_API_URL}/auth/device-code"
    req = urllib.request.Request(url, method="POST", data=b"")
    req.add_header("User-Agent", "initrunner-hub-client")
    req.add_header("Content-Type", "application/json")

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.URLError as e:
        raise HubError("Could not reach InitHub. Check your connection.") from e


def poll_device_code(device_code: str) -> dict:
    """Poll device code status.

    Returns dict with status ("pending" or "complete") and on complete: token, username.
    Raises HubDeviceCodeExpired for expired codes, HubError for invalid/consumed.
    """
    url = f"{INITHUB_API_URL}/auth/device-code/poll"
    body = json.dumps({"device_code": device_code}).encode()
    req = urllib.request.Request(url, method="POST", data=body)
    req.add_header("User-Agent", "initrunner-hub-client")
    req.add_header("Content-Type", "application/json")

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        resp_body = e.read().decode("utf-8", errors="replace")
        detail = ""
        try:
            detail = json.loads(resp_body).get("detail", "")
        except (json.JSONDecodeError, AttributeError):
            detail = resp_body
        if "expired" in detail.lower():
            raise HubDeviceCodeExpired("Device code has expired. Please try again.") from e
        raise HubError(f"Device code error: {detail}") from e
    except urllib.error.URLError as e:
        raise HubError("Could not reach InitHub. Check your connection.") from e


# Hub reference parsing

_HUB_RE_STR = r"^hub:(?P<owner>[a-zA-Z0-9_.-]+)/(?P<name>[a-zA-Z0-9_.-]+)(?:@(?P<version>.+))?$"


def is_hub_reference(source: str) -> bool:
    """Check if a source string is a hub:owner/name[@version] reference."""
    import re

    return bool(re.match(_HUB_RE_STR, source))


def parse_hub_reference(source: str) -> tuple[str, str, str | None]:
    """Parse hub:owner/name[@version] into (owner, name, version)."""
    import re

    m = re.match(_HUB_RE_STR, source)
    if not m:
        raise ValueError(f"Invalid hub reference: {source}")
    return m.group("owner"), m.group("name"), m.group("version")


# Flexible source parsing (accepts both owner/name[@ver] and hub:owner/name[@ver])

_SOURCE_RE_STR = (
    r"^(?:hub:)?(?P<owner>[a-zA-Z0-9_.-]+)/(?P<name>[a-zA-Z0-9_.-]+)"
    r"(?:@(?P<version>.+))?$"
)


def parse_hub_source(source: str) -> tuple[str, str, str | None]:
    """Parse owner/name[@ver] or hub:owner/name[@ver]."""
    import re

    m = re.match(_SOURCE_RE_STR, source)
    if not m:
        raise ValueError(f"Invalid source: {source}")
    return m.group("owner"), m.group("name"), m.group("version")
