"""OCI Distribution API client for publishing and pulling role bundles."""

from __future__ import annotations

import hashlib
import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from initrunner.packaging.auth import OCIAuth, resolve_auth

logger = logging.getLogger(__name__)

OCI_CONFIG_MEDIA_TYPE = "application/vnd.initrunner.config.v1+json"
OCI_LAYER_MEDIA_TYPE = "application/vnd.initrunner.role.v1.tar+gzip"
OCI_MANIFEST_MEDIA_TYPE = "application/vnd.oci.image.manifest.v1+json"


class OCIError(Exception):
    """Base error for OCI operations."""


@dataclass
class OCIRef:
    registry: str
    repository: str
    tag: str
    digest: str = ""
    insecure: bool = False

    @property
    def base_url(self) -> str:
        scheme = "http" if self.insecure else "https"
        return f"{scheme}://{self.registry}"

    @property
    def api_prefix(self) -> str:
        return f"{self.base_url}/v2/{self.repository}"


def is_oci_reference(source: str) -> bool:
    """Check if a source string is an OCI reference."""
    return source.startswith("oci://")


def _is_localhost(registry: str) -> bool:
    """Check if a registry hostname is localhost or 127.0.0.1."""
    host = registry.split(":")[0]
    return host in ("localhost", "127.0.0.1")


def parse_oci_ref(source: str) -> OCIRef:
    """Parse an OCI reference string into components.

    Expected format: oci://registry/repository[:tag][@digest]
    """
    ref = source
    if ref.startswith("oci://"):
        ref = ref[6:]

    digest = ""
    if "@" in ref:
        ref, digest = ref.rsplit("@", 1)

    tag = "latest"
    if ":" in ref:
        # Split on last colon — but only if it's after the registry part
        # registry/repo:tag — find the colon that separates repo from tag
        parts = ref.split("/", 1)
        if len(parts) == 1:
            raise OCIError(f"Invalid OCI reference: '{source}' (missing repository)")
        registry_part = parts[0]
        repo_and_tag = parts[1]

        if ":" in repo_and_tag:
            repo, tag = repo_and_tag.rsplit(":", 1)
        else:
            repo = repo_and_tag

        result = OCIRef(registry=registry_part, repository=repo, tag=tag, digest=digest)
        result.insecure = _is_localhost(registry_part)
        return result

    parts = ref.split("/", 1)
    if len(parts) < 2:
        raise OCIError(f"Invalid OCI reference: '{source}' (missing repository)")

    result = OCIRef(registry=parts[0], repository=parts[1], tag=tag, digest=digest)
    result.insecure = _is_localhost(parts[0])
    return result


class OCIClient:
    """Synchronous OCI Distribution API client using urllib."""

    def __init__(self, ref: OCIRef) -> None:
        self.ref = ref
        self._token: str | None = None
        self._auth: OCIAuth | None = resolve_auth(ref.registry)

    def push(self, bundle_path: Path, config_data: dict) -> str:
        """Upload a bundle as an OCI artifact. Returns the manifest digest."""
        # 1. Upload config blob
        config_bytes = json.dumps(config_data, indent=2).encode()
        config_digest = f"sha256:{hashlib.sha256(config_bytes).hexdigest()}"
        self._upload_blob(config_bytes, config_digest)

        # 2. Upload layer blob (the tar.gz bundle)
        layer_data = bundle_path.read_bytes()
        layer_digest = f"sha256:{hashlib.sha256(layer_data).hexdigest()}"
        self._upload_blob(layer_data, layer_digest)

        # 3. PUT OCI manifest
        manifest = {
            "schemaVersion": 2,
            "mediaType": OCI_MANIFEST_MEDIA_TYPE,
            "config": {
                "mediaType": OCI_CONFIG_MEDIA_TYPE,
                "digest": config_digest,
                "size": len(config_bytes),
            },
            "layers": [
                {
                    "mediaType": OCI_LAYER_MEDIA_TYPE,
                    "digest": layer_digest,
                    "size": len(layer_data),
                }
            ],
        }

        manifest_bytes = json.dumps(manifest, indent=2).encode()
        manifest_digest = f"sha256:{hashlib.sha256(manifest_bytes).hexdigest()}"

        url = f"{self.ref.api_prefix}/manifests/{self.ref.tag}"
        try:
            with self._urlopen_with_auth(
                url,
                method="PUT",
                data=manifest_bytes,
                headers={"Content-Type": OCI_MANIFEST_MEDIA_TYPE},
                timeout=60,
            ) as resp:
                return resp.headers.get("Docker-Content-Digest", manifest_digest)
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace")
            raise OCIError(f"Failed to push manifest: HTTP {e.code}: {body}") from e

    def pull(self, target_dir: Path) -> Path:
        """Download an OCI artifact and extract the bundle. Returns extracted path."""
        # 1. GET manifest
        tag_or_digest = self.ref.digest or self.ref.tag
        url = f"{self.ref.api_prefix}/manifests/{tag_or_digest}"

        try:
            with self._urlopen_with_auth(
                url, headers={"Accept": OCI_MANIFEST_MEDIA_TYPE}, timeout=60
            ) as resp:
                manifest = json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise OCIError(
                    f"Artifact not found: {self.ref.registry}/{self.ref.repository}:{tag_or_digest}"
                ) from e
            raise OCIError(f"Failed to fetch manifest: HTTP {e.code}") from e

        # 2. Download the layer blob
        if not manifest.get("layers"):
            raise OCIError("OCI manifest has no layers")

        layer = manifest["layers"][0]
        layer_digest = layer["digest"]

        blob_url = f"{self.ref.api_prefix}/blobs/{layer_digest}"

        try:
            with self._urlopen_with_auth(blob_url, timeout=120) as resp:
                layer_data = resp.read()
        except urllib.error.HTTPError as e:
            raise OCIError(f"Failed to download layer: HTTP {e.code}") from e

        # Verify digest
        actual = f"sha256:{hashlib.sha256(layer_data).hexdigest()}"
        if actual != layer_digest:
            raise OCIError(f"Layer digest mismatch: expected {layer_digest}, got {actual}")

        # 3. Save and extract
        target_dir.mkdir(parents=True, exist_ok=True)
        archive_path = target_dir / "bundle.tar.gz"
        archive_path.write_bytes(layer_data)

        from initrunner.packaging.bundle import extract_bundle

        extract_bundle(archive_path, target_dir)
        archive_path.unlink()

        return target_dir

    def head(self) -> dict:
        """Check if artifact exists and return metadata."""
        tag_or_digest = self.ref.digest or self.ref.tag
        url = f"{self.ref.api_prefix}/manifests/{tag_or_digest}"

        try:
            with self._urlopen_with_auth(
                url,
                method="HEAD",
                headers={"Accept": OCI_MANIFEST_MEDIA_TYPE},
                timeout=30,
            ) as resp:
                return {
                    "digest": resp.headers.get("Docker-Content-Digest", ""),
                    "content_type": resp.headers.get("Content-Type", ""),
                    "content_length": resp.headers.get("Content-Length", ""),
                }
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise OCIError("Artifact not found") from e
            raise OCIError(f"HEAD request failed: HTTP {e.code}") from e

    def _upload_blob(self, data: bytes, digest: str) -> None:
        """Upload a blob via POST (initiate) + PUT (complete) flow."""
        # POST to initiate upload
        url = f"{self.ref.api_prefix}/blobs/uploads/"

        try:
            with self._urlopen_with_auth(
                url,
                method="POST",
                data=b"",
                headers={"Content-Length": "0"},
                timeout=30,
            ) as resp:
                upload_url = resp.headers.get("Location", "")
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace")
            raise OCIError(f"Failed to initiate blob upload: HTTP {e.code}: {body}") from e

        if not upload_url:
            raise OCIError("No Location header in upload initiation response")

        # Make upload URL absolute if relative
        if upload_url.startswith("/"):
            upload_url = f"{self.ref.base_url}{upload_url}"

        # PUT to complete upload
        separator = "&" if "?" in upload_url else "?"
        put_url = f"{upload_url}{separator}digest={digest}"

        try:
            self._urlopen_with_auth(
                put_url,
                method="PUT",
                data=data,
                headers={
                    "Content-Type": "application/octet-stream",
                    "Content-Length": str(len(data)),
                },
                timeout=120,
            )
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace")
            raise OCIError(f"Failed to upload blob: HTTP {e.code}: {body}") from e

    def _get_token(self, www_authenticate: str) -> str:
        """Handle WWW-Authenticate challenge for token exchange."""
        # Parse: Bearer realm="...",service="...",scope="..."
        params: dict[str, str] = {}
        if www_authenticate.startswith("Bearer "):
            parts = www_authenticate[7:]
            for part in parts.split(","):
                part = part.strip()
                if "=" in part:
                    key, val = part.split("=", 1)
                    params[key.strip()] = val.strip('"')

        realm = params.get("realm", "")
        if not realm:
            raise OCIError("No realm in WWW-Authenticate header")

        token_url = realm
        query_parts = []
        if "service" in params:
            query_parts.append(f"service={urllib.parse.quote(params['service'])}")
        if "scope" in params:
            query_parts.append(f"scope={urllib.parse.quote(params['scope'])}")
        if query_parts:
            token_url = f"{token_url}?{'&'.join(query_parts)}"

        req = urllib.request.Request(token_url)
        req.add_header("User-Agent", "initrunner-oci")

        # Add basic auth for token exchange if credentials available
        if self._auth:
            import base64

            creds = base64.b64encode(
                f"{self._auth.username}:{self._auth.password}".encode()
            ).decode()
            req.add_header("Authorization", f"Basic {creds}")

        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode())
                return data.get("token") or data.get("access_token", "")
        except urllib.error.HTTPError as e:
            raise OCIError(f"Token exchange failed: HTTP {e.code}") from e

    def _build_request(
        self,
        url: str,
        *,
        method: str = "GET",
        data: bytes | None = None,
    ) -> urllib.request.Request:
        """Build a urllib Request with auth headers."""
        req = urllib.request.Request(url, method=method, data=data)
        req.add_header("User-Agent", "initrunner-oci")

        if self._token:
            req.add_header("Authorization", f"Bearer {self._token}")
        elif self._auth:
            import base64

            creds = base64.b64encode(
                f"{self._auth.username}:{self._auth.password}".encode()
            ).decode()
            req.add_header("Authorization", f"Basic {creds}")

        return req

    def _urlopen_with_auth(
        self,
        url: str,
        *,
        method: str = "GET",
        data: bytes | None = None,
        headers: dict[str, str] | None = None,
        timeout: int = 60,
    ) -> Any:
        """Open a URL, handling 401 challenges with token exchange. Returns response."""
        req = self._build_request(url, method=method, data=data)
        if headers:
            for k, v in headers.items():
                req.add_header(k, v)

        try:
            return urllib.request.urlopen(req, timeout=timeout)
        except urllib.error.HTTPError as e:
            if e.code != 401:
                raise
            www_auth = e.headers.get("WWW-Authenticate", "")
            if not www_auth:
                raise
            self._token = self._get_token(www_auth)
            req = self._build_request(url, method=method, data=data)
            if headers:
                for k, v in headers.items():
                    req.add_header(k, v)
            return urllib.request.urlopen(req, timeout=timeout)
