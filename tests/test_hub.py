"""Tests for the InitHub API client."""

from __future__ import annotations

import json
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest

from initrunner.hub import (
    HubAuthError,
    HubDeviceCodeExpired,
    HubError,
    HubPackageInfo,
    _hub_request,
    hub_download,
    hub_publish,
    hub_search,
    is_hub_reference,
    load_hub_token,
    parse_hub_reference,
    parse_hub_source,
    poll_device_code,
    remove_hub_token,
    request_device_code,
    save_hub_token,
)

# ---------------------------------------------------------------------------
# Hub reference parsing
# ---------------------------------------------------------------------------


class TestIsHubReference:
    def test_valid_simple(self):
        assert is_hub_reference("hub:owner/name") is True

    def test_valid_with_version(self):
        assert is_hub_reference("hub:owner/name@1.0.0") is True

    def test_valid_with_dots_hyphens(self):
        assert is_hub_reference("hub:my-org.io/my-agent.pack") is True

    def test_valid_with_underscores(self):
        assert is_hub_reference("hub:my_org/my_agent") is True

    def test_invalid_no_prefix(self):
        assert is_hub_reference("owner/name") is False

    def test_invalid_oci_prefix(self):
        assert is_hub_reference("oci://registry/repo") is False

    def test_invalid_no_slash(self):
        assert is_hub_reference("hub:justname") is False

    def test_invalid_empty(self):
        assert is_hub_reference("") is False

    def test_invalid_github_prefix(self):
        assert is_hub_reference("github:owner/repo") is False


class TestParseHubReference:
    def test_simple(self):
        owner, name, version = parse_hub_reference("hub:owner/name")
        assert owner == "owner"
        assert name == "name"
        assert version is None

    def test_with_version(self):
        owner, name, version = parse_hub_reference("hub:owner/name@2.1.0")
        assert owner == "owner"
        assert name == "name"
        assert version == "2.1.0"

    def test_with_semver_prefix(self):
        _owner, _name, version = parse_hub_reference("hub:owner/name@v1.0.0")
        assert version == "v1.0.0"

    def test_with_dots_hyphens(self):
        owner, name, version = parse_hub_reference("hub:my-org/my-pack@latest")
        assert owner == "my-org"
        assert name == "my-pack"
        assert version == "latest"

    def test_invalid_raises(self):
        with pytest.raises(ValueError, match="Invalid hub reference"):
            parse_hub_reference("not-a-hub-ref")

    def test_invalid_no_slash_raises(self):
        with pytest.raises(ValueError, match="Invalid hub reference"):
            parse_hub_reference("hub:justname")


class TestParseHubSource:
    """Tests for the flexible source parser (accepts both owner/name and hub:owner/name)."""

    def test_simple_owner_name(self):
        owner, name, version = parse_hub_source("owner/name")
        assert owner == "owner"
        assert name == "name"
        assert version is None

    def test_owner_name_with_version(self):
        owner, name, version = parse_hub_source("owner/name@2.1.0")
        assert owner == "owner"
        assert name == "name"
        assert version == "2.1.0"

    def test_hub_prefix(self):
        owner, name, version = parse_hub_source("hub:owner/name")
        assert owner == "owner"
        assert name == "name"
        assert version is None

    def test_hub_prefix_with_version(self):
        owner, name, version = parse_hub_source("hub:owner/name@1.0.0")
        assert owner == "owner"
        assert name == "name"
        assert version == "1.0.0"

    def test_dots_and_hyphens(self):
        owner, name, version = parse_hub_source("my-org.io/my-agent.pack@latest")
        assert owner == "my-org.io"
        assert name == "my-agent.pack"
        assert version == "latest"

    def test_underscores(self):
        owner, name, version = parse_hub_source("my_org/my_agent")
        assert owner == "my_org"
        assert name == "my_agent"
        assert version is None

    def test_invalid_bare_name_raises(self):
        with pytest.raises(ValueError, match="Invalid source"):
            parse_hub_source("justname")

    def test_invalid_empty_raises(self):
        with pytest.raises(ValueError, match="Invalid source"):
            parse_hub_source("")

    def test_oci_prefix_raises(self):
        with pytest.raises(ValueError, match="Invalid source"):
            parse_hub_source("oci://registry/repo")


# ---------------------------------------------------------------------------
# Token storage
# ---------------------------------------------------------------------------


class TestTokenStorage:
    def test_save_and_load(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "initrunner.hub.get_hub_auth_path",
            lambda: tmp_path / "hub-auth.json",
        )
        save_hub_token("test-token-123")
        assert load_hub_token() == "test-token-123"

    def test_load_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "initrunner.hub.get_hub_auth_path",
            lambda: tmp_path / "nonexistent" / "hub-auth.json",
        )
        assert load_hub_token() is None

    def test_load_corrupt_json(self, tmp_path, monkeypatch):
        auth_path = tmp_path / "hub-auth.json"
        auth_path.write_text("not json{{{")
        monkeypatch.setattr(
            "initrunner.hub.get_hub_auth_path",
            lambda: auth_path,
        )
        assert load_hub_token() is None

    def test_remove(self, tmp_path, monkeypatch):
        auth_path = tmp_path / "hub-auth.json"
        auth_path.write_text(json.dumps({"token": "abc"}))
        monkeypatch.setattr(
            "initrunner.hub.get_hub_auth_path",
            lambda: auth_path,
        )
        remove_hub_token()
        assert not auth_path.exists()

    def test_remove_nonexistent(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "initrunner.hub.get_hub_auth_path",
            lambda: tmp_path / "nonexistent.json",
        )
        # Should not raise
        remove_hub_token()

    def test_save_creates_parent_dir(self, tmp_path, monkeypatch):
        auth_path = tmp_path / "subdir" / "hub-auth.json"
        monkeypatch.setattr(
            "initrunner.hub.get_hub_auth_path",
            lambda: auth_path,
        )
        save_hub_token("token-xyz")
        assert auth_path.exists()
        assert load_hub_token() == "token-xyz"


# ---------------------------------------------------------------------------
# _hub_request
# ---------------------------------------------------------------------------


class TestHubRequest:
    def _mock_response(self, data: dict, status: int = 200) -> MagicMock:
        body = json.dumps(data).encode()
        resp = MagicMock()
        resp.read.return_value = body
        resp.status = status
        resp.__enter__ = MagicMock(return_value=resp)
        resp.__exit__ = MagicMock(return_value=False)
        return resp

    def test_get_success(self):
        resp = self._mock_response({"ok": True})
        with patch("initrunner.hub.urllib.request.urlopen", return_value=resp):
            result = _hub_request("/test")
        assert result == {"ok": True}

    def test_empty_response(self):
        resp = MagicMock()
        resp.read.return_value = b""
        resp.__enter__ = MagicMock(return_value=resp)
        resp.__exit__ = MagicMock(return_value=False)
        with patch("initrunner.hub.urllib.request.urlopen", return_value=resp):
            result = _hub_request("/test")
        assert result == {}

    def test_401_raises_auth_error(self):
        import urllib.error

        error = urllib.error.HTTPError(
            "http://example.com",
            401,
            "Unauthorized",
            {},  # type: ignore[arg-type]
            BytesIO(b"denied"),
        )
        with patch("initrunner.hub.urllib.request.urlopen", side_effect=error):
            with pytest.raises(HubAuthError, match="Authentication failed"):
                _hub_request("/test")

    def test_404_raises_hub_error(self):
        import urllib.error

        error = urllib.error.HTTPError(
            "http://example.com",
            404,
            "Not Found",
            {},  # type: ignore[arg-type]
            BytesIO(b"not found"),
        )
        with patch("initrunner.hub.urllib.request.urlopen", side_effect=error):
            with pytest.raises(HubError, match="Not found"):
                _hub_request("/test")

    def test_500_raises_hub_error(self):
        import urllib.error

        error = urllib.error.HTTPError(
            "http://example.com",
            500,
            "Server Error",
            {},  # type: ignore[arg-type]
            BytesIO(b"oops"),
        )
        with patch("initrunner.hub.urllib.request.urlopen", side_effect=error):
            with pytest.raises(HubError, match="HTTP 500"):
                _hub_request("/test")

    def test_url_error_raises_hub_error(self):
        import urllib.error

        error = urllib.error.URLError("Connection refused")
        with patch("initrunner.hub.urllib.request.urlopen", side_effect=error):
            with pytest.raises(HubError, match="Could not reach InitHub"):
                _hub_request("/test")

    def test_auth_header_sent(self):
        resp = self._mock_response({"ok": True})
        with patch("initrunner.hub.urllib.request.urlopen", return_value=resp) as mock_urlopen:
            _hub_request("/test", token="my-token")
        req = mock_urlopen.call_args[0][0]
        assert req.get_header("Authorization") == "Bearer my-token"


# ---------------------------------------------------------------------------
# hub_search
# ---------------------------------------------------------------------------


class TestHubSearch:
    def test_search_returns_results(self):
        api_response = {
            "items": [
                {
                    "slug": "code-reviewer",
                    "description": "Reviews code",
                    "owner": {"username": "alice"},
                    "downloads_total": 42,
                    "latest_version": {
                        "version": "1.2.0",
                        "tags": ["code", "review"],
                    },
                },
                {
                    "slug": "summarizer",
                    "description": "Summarizes text",
                    "owner": {"username": "bob"},
                    "downloads_total": 10,
                    "latest_version": {
                        "version": "0.5.0",
                        "tags": ["text"],
                    },
                },
            ]
        }
        with patch("initrunner.hub._hub_request", return_value=api_response):
            results = hub_search("code")

        assert len(results) == 2
        assert results[0].owner == "alice"
        assert results[0].name == "code-reviewer"
        assert results[0].downloads == 42
        assert results[0].latest_version == "1.2.0"
        assert results[0].tags == ["code", "review"]

    def test_search_empty_results(self):
        with patch("initrunner.hub._hub_request", return_value={"items": []}):
            results = hub_search("nothing")
        assert results == []

    def test_search_no_latest_version(self):
        api_response = {
            "items": [
                {
                    "slug": "new-pack",
                    "description": "Brand new",
                    "owner": {"username": "charlie"},
                    "downloads_total": 0,
                    "latest_version": None,
                },
            ]
        }
        with patch("initrunner.hub._hub_request", return_value=api_response):
            results = hub_search("new")

        assert len(results) == 1
        assert results[0].latest_version == ""
        assert results[0].tags == []


# ---------------------------------------------------------------------------
# hub_download
# ---------------------------------------------------------------------------


class TestHubDownload:
    def test_download_with_version(self):
        bundle_bytes = b"fake-bundle-data"
        resp = MagicMock()
        resp.read.return_value = bundle_bytes
        resp.__enter__ = MagicMock(return_value=resp)
        resp.__exit__ = MagicMock(return_value=False)
        with patch("initrunner.hub.urllib.request.urlopen", return_value=resp):
            result = hub_download("owner", "name", "1.0.0")
        assert result == bundle_bytes

    def test_download_without_version_resolves_latest(self):
        bundle_bytes = b"fake-bundle-data"
        resp = MagicMock()
        resp.read.return_value = bundle_bytes
        resp.__enter__ = MagicMock(return_value=resp)
        resp.__exit__ = MagicMock(return_value=False)

        mock_info = HubPackageInfo(
            owner="owner",
            name="name",
            description="desc",
            latest_version="2.0.0",
        )
        with (
            patch("initrunner.hub.hub_resolve", return_value=mock_info),
            patch("initrunner.hub.urllib.request.urlopen", return_value=resp),
        ):
            result = hub_download("owner", "name")
        assert result == bundle_bytes

    def test_download_no_versions_raises(self):
        mock_info = HubPackageInfo(
            owner="owner",
            name="name",
            description="desc",
            latest_version="",
        )
        with patch("initrunner.hub.hub_resolve", return_value=mock_info):
            with pytest.raises(HubError, match="No versions published"):
                hub_download("owner", "name")

    def test_download_404_raises(self):
        import urllib.error

        error = urllib.error.HTTPError("http://example.com", 404, "Not Found", {}, BytesIO(b""))  # type: ignore[arg-type]
        with patch("initrunner.hub.urllib.request.urlopen", side_effect=error):
            with pytest.raises(HubError, match="Package not found"):
                hub_download("owner", "name", "1.0.0")


# ---------------------------------------------------------------------------
# hub_publish
# ---------------------------------------------------------------------------


class TestHubPublish:
    def test_publish_constructs_multipart(self, tmp_path):
        bundle_file = tmp_path / "test-bundle.tar.gz"
        bundle_file.write_bytes(b"fake-bundle-content")

        api_response = {"owner": "alice", "name": "my-pack", "version": "1.0.0"}
        with patch("initrunner.hub._hub_request", return_value=api_response) as mock_req:
            result = hub_publish(
                str(bundle_file),
                "test-token",
                readme="# My Pack",
                repository_url="https://github.com/alice/my-pack",
                categories=["code", "review"],
            )

        assert result == api_response

        # Verify the request was made with POST and multipart content type
        call_kwargs = mock_req.call_args
        assert call_kwargs.kwargs["method"] == "POST"
        assert call_kwargs.kwargs["token"] == "test-token"
        assert "multipart/form-data" in call_kwargs.kwargs["content_type"]

        # Verify the body contains expected parts
        body = call_kwargs.kwargs["data"]
        assert b"fake-bundle-content" in body
        assert b"# My Pack" in body
        assert b"https://github.com/alice/my-pack" in body
        assert b'["code", "review"]' in body

    def test_publish_minimal(self, tmp_path):
        bundle_file = tmp_path / "test-bundle.tar.gz"
        bundle_file.write_bytes(b"content")

        api_response = {"owner": "bob", "name": "pack", "version": "0.1.0"}
        with patch("initrunner.hub._hub_request", return_value=api_response) as mock_req:
            result = hub_publish(str(bundle_file), "token")

        assert result == api_response
        body = mock_req.call_args.kwargs["data"]
        # Should not contain readme or repository_url fields
        assert b'name="readme"' not in body
        assert b'name="repository_url"' not in body
        assert b'name="categories"' not in body


# ---------------------------------------------------------------------------
# request_device_code
# ---------------------------------------------------------------------------


class TestRequestDeviceCode:
    def _mock_response(self, data: dict) -> MagicMock:
        body = json.dumps(data).encode()
        resp = MagicMock()
        resp.read.return_value = body
        resp.__enter__ = MagicMock(return_value=resp)
        resp.__exit__ = MagicMock(return_value=False)
        return resp

    def test_success(self):
        response_data = {
            "device_code": "dc-abc",
            "user_code": "ABCD-1234",
            "verification_url": "https://hub.initrunner.ai/cli-auth?code=ABCD-1234",
            "interval_seconds": 5,
            "expires_at": "2026-03-18T12:00:00+00:00",
        }
        resp = self._mock_response(response_data)
        with patch("initrunner.hub.urllib.request.urlopen", return_value=resp):
            result = request_device_code()
        assert result == response_data

    def test_network_error(self):
        import urllib.error

        error = urllib.error.URLError("Connection refused")
        with patch("initrunner.hub.urllib.request.urlopen", side_effect=error):
            with pytest.raises(HubError, match="Could not reach InitHub"):
                request_device_code()


# ---------------------------------------------------------------------------
# poll_device_code
# ---------------------------------------------------------------------------


class TestPollDeviceCode:
    def _mock_response(self, data: dict) -> MagicMock:
        body = json.dumps(data).encode()
        resp = MagicMock()
        resp.read.return_value = body
        resp.__enter__ = MagicMock(return_value=resp)
        resp.__exit__ = MagicMock(return_value=False)
        return resp

    def test_pending(self):
        resp = self._mock_response({"status": "pending"})
        with patch("initrunner.hub.urllib.request.urlopen", return_value=resp):
            result = poll_device_code("dc-abc")
        assert result == {"status": "pending"}

    def test_complete(self):
        response_data = {"status": "complete", "token": "tok-xyz", "username": "alice"}
        resp = self._mock_response(response_data)
        with patch("initrunner.hub.urllib.request.urlopen", return_value=resp):
            result = poll_device_code("dc-abc")
        assert result == response_data

    def test_expired_raises_device_code_expired(self):
        import urllib.error

        error = urllib.error.HTTPError(
            "http://example.com",
            400,
            "Bad Request",
            {},  # type: ignore[arg-type]
            BytesIO(json.dumps({"detail": "Device code expired"}).encode()),
        )
        with patch("initrunner.hub.urllib.request.urlopen", side_effect=error):
            with pytest.raises(HubDeviceCodeExpired, match="expired"):
                poll_device_code("dc-abc")

    def test_invalid_raises_hub_error(self):
        import urllib.error

        error = urllib.error.HTTPError(
            "http://example.com",
            400,
            "Bad Request",
            {},  # type: ignore[arg-type]
            BytesIO(json.dumps({"detail": "Invalid device code"}).encode()),
        )
        with patch("initrunner.hub.urllib.request.urlopen", side_effect=error):
            with pytest.raises(HubError, match="Invalid device code"):
                poll_device_code("dc-abc")

    def test_consumed_raises_hub_error(self):
        import urllib.error

        error = urllib.error.HTTPError(
            "http://example.com",
            400,
            "Bad Request",
            {},  # type: ignore[arg-type]
            BytesIO(json.dumps({"detail": "Device code already consumed"}).encode()),
        )
        with patch("initrunner.hub.urllib.request.urlopen", side_effect=error):
            with pytest.raises(HubError, match="already consumed"):
                poll_device_code("dc-abc")
