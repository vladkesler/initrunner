"""Tests for OCI reference parsing and client."""

import json
from unittest.mock import MagicMock, patch

import pytest

from initrunner.packaging.oci import (
    OCIError,
    OCIRef,
    is_oci_reference,
    parse_oci_ref,
)


class TestIsOCIReference:
    def test_oci_prefix(self):
        assert is_oci_reference("oci://ghcr.io/org/repo") is True

    def test_github_source(self):
        assert is_oci_reference("user/repo") is False

    def test_bare_name(self):
        assert is_oci_reference("my-role") is False

    def test_dotted_github_source(self):
        assert is_oci_reference("my-user.name/my-repo.name") is False

    def test_empty_string(self):
        assert is_oci_reference("") is False


class TestParseOCIRef:
    def test_basic_ref(self):
        ref = parse_oci_ref("oci://ghcr.io/org/my-agent")
        assert ref.registry == "ghcr.io"
        assert ref.repository == "org/my-agent"
        assert ref.tag == "latest"

    def test_ref_with_tag(self):
        ref = parse_oci_ref("oci://ghcr.io/org/my-agent:1.0.0")
        assert ref.registry == "ghcr.io"
        assert ref.repository == "org/my-agent"
        assert ref.tag == "1.0.0"

    def test_ref_with_digest(self):
        ref = parse_oci_ref("oci://ghcr.io/org/my-agent@sha256:abc123")
        assert ref.registry == "ghcr.io"
        assert ref.repository == "org/my-agent"
        assert ref.digest == "sha256:abc123"

    def test_ref_with_tag_and_digest(self):
        ref = parse_oci_ref("oci://ghcr.io/org/my-agent:1.0@sha256:abc123")
        assert ref.registry == "ghcr.io"
        assert ref.repository == "org/my-agent"
        assert ref.tag == "1.0"
        assert ref.digest == "sha256:abc123"

    def test_docker_hub_ref(self):
        ref = parse_oci_ref("oci://docker.io/library/my-agent:latest")
        assert ref.registry == "docker.io"
        assert ref.repository == "library/my-agent"
        assert ref.tag == "latest"

    def test_nested_repo(self):
        ref = parse_oci_ref("oci://ghcr.io/org/team/my-agent:v2")
        assert ref.registry == "ghcr.io"
        assert ref.repository == "org/team/my-agent"
        assert ref.tag == "v2"

    def test_without_oci_prefix(self):
        ref = parse_oci_ref("ghcr.io/org/my-agent:1.0")
        assert ref.registry == "ghcr.io"
        assert ref.repository == "org/my-agent"
        assert ref.tag == "1.0"

    def test_missing_repository(self):
        with pytest.raises(OCIError, match="missing repository"):
            parse_oci_ref("oci://ghcr.io")

    def test_api_prefix(self):
        ref = parse_oci_ref("oci://ghcr.io/org/my-agent")
        assert ref.api_prefix == "https://ghcr.io/v2/org/my-agent"

    def test_base_url(self):
        ref = parse_oci_ref("oci://ghcr.io/org/my-agent")
        assert ref.base_url == "https://ghcr.io"


class TestOCIClient:
    def test_push_flow(self, tmp_path):
        """Test push with mocked HTTP responses."""
        from initrunner.packaging.oci import OCIClient

        ref = OCIRef(registry="ghcr.io", repository="org/test", tag="1.0")

        with patch("initrunner.packaging.oci.resolve_auth", return_value=None):
            client = OCIClient(ref)

        # Mock the HTTP calls
        bundle_path = tmp_path / "test.tar.gz"
        bundle_path.write_bytes(b"fake bundle content")

        config_data = {"name": "test", "version": "1.0"}

        mock_upload_resp = MagicMock()
        mock_upload_resp.headers = {"Location": "/v2/org/test/blobs/uploads/123"}
        mock_upload_resp.__enter__ = MagicMock(return_value=mock_upload_resp)
        mock_upload_resp.__exit__ = MagicMock(return_value=False)

        mock_put_resp = MagicMock()
        mock_put_resp.__enter__ = MagicMock(return_value=mock_put_resp)
        mock_put_resp.__exit__ = MagicMock(return_value=False)

        mock_manifest_resp = MagicMock()
        mock_manifest_resp.headers = {"Docker-Content-Digest": "sha256:test123"}
        mock_manifest_resp.__enter__ = MagicMock(return_value=mock_manifest_resp)
        mock_manifest_resp.__exit__ = MagicMock(return_value=False)

        responses = [
            # blob upload initiate (config)
            mock_upload_resp,
            # blob upload complete (config)
            mock_put_resp,
            # blob upload initiate (layer)
            mock_upload_resp,
            # blob upload complete (layer)
            mock_put_resp,
            # manifest PUT
            mock_manifest_resp,
        ]

        with patch("urllib.request.urlopen", side_effect=responses):
            digest = client.push(bundle_path, config_data)

        assert digest == "sha256:test123"

    def test_pull_flow(self, tmp_path):
        """Test pull with mocked HTTP responses."""
        import hashlib
        import io
        import tarfile

        from initrunner.packaging.bundle import BundleFile, BundleManifest
        from initrunner.packaging.oci import OCIClient

        ref = OCIRef(registry="ghcr.io", repository="org/test", tag="latest")

        with patch("initrunner.packaging.oci.resolve_auth", return_value=None):
            client = OCIClient(ref)

        # Create a valid bundle in memory
        role_content = (
            b"apiVersion: initrunner/v1\nkind: Agent\n"
            b"metadata:\n  name: test-agent\n"
            b"spec:\n  role: test\n  model:\n"
            b"    provider: openai\n    name: gpt-5-mini\n"
        )
        role_sha = hashlib.sha256(role_content).hexdigest()

        manifest = BundleManifest(
            name="test-agent",
            version="1.0.0",
            files=[
                BundleFile(
                    path="role.yaml",
                    sha256=role_sha,
                    size=len(role_content),
                    kind="role",
                )
            ],
        )

        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            manifest_bytes = manifest.model_dump_json(indent=2).encode()
            info = tarfile.TarInfo(name="manifest.json")
            info.size = len(manifest_bytes)
            tar.addfile(info, io.BytesIO(manifest_bytes))

            info = tarfile.TarInfo(name="role.yaml")
            info.size = len(role_content)
            tar.addfile(info, io.BytesIO(role_content))

        bundle_bytes = buf.getvalue()
        layer_digest = f"sha256:{hashlib.sha256(bundle_bytes).hexdigest()}"

        oci_manifest = {
            "schemaVersion": 2,
            "layers": [{"digest": layer_digest, "size": len(bundle_bytes)}],
        }

        mock_manifest_resp = MagicMock()
        mock_manifest_resp.read.return_value = json.dumps(oci_manifest).encode()
        mock_manifest_resp.__enter__ = MagicMock(return_value=mock_manifest_resp)
        mock_manifest_resp.__exit__ = MagicMock(return_value=False)

        mock_blob_resp = MagicMock()
        mock_blob_resp.read.return_value = bundle_bytes
        mock_blob_resp.__enter__ = MagicMock(return_value=mock_blob_resp)
        mock_blob_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", side_effect=[mock_manifest_resp, mock_blob_resp]):
            target = tmp_path / "extracted"
            result = client.pull(target)

        assert (result / "role.yaml").exists()
        assert (result / "manifest.json").exists()

    def test_head_not_found(self):
        """HEAD request returns 404."""
        import urllib.error

        from initrunner.packaging.oci import OCIClient

        ref = OCIRef(registry="ghcr.io", repository="org/test", tag="latest")

        with patch("initrunner.packaging.oci.resolve_auth", return_value=None):
            client = OCIClient(ref)

        from email.message import Message

        hdrs = Message()
        error = urllib.error.HTTPError("url", 404, "Not Found", hdrs, None)
        with patch("urllib.request.urlopen", side_effect=error):
            with pytest.raises(OCIError, match="not found"):
                client.head()
