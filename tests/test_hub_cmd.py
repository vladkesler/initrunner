"""Tests for the InitHub CLI commands."""

from __future__ import annotations

from unittest.mock import patch

import typer
from typer.testing import CliRunner

from initrunner.hub import HubError, HubPackageInfo, HubSearchResult

# Build a minimal app that includes the hub sub-app for testing
app = typer.Typer()

from initrunner.cli.hub_cmd import app as hub_app  # noqa: E402

app.add_typer(hub_app, name="hub")

runner = CliRunner()


# ---------------------------------------------------------------------------
# hub login
# ---------------------------------------------------------------------------


class TestHubLogin:
    def test_login_saves_token(self):
        with patch("initrunner.hub.save_hub_token") as mock_save:
            result = runner.invoke(app, ["hub", "login"], input="my-secret-token\n")
        assert result.exit_code == 0
        assert "Token saved" in result.output
        mock_save.assert_called_once_with("my-secret-token")

    def test_login_strips_whitespace(self):
        with patch("initrunner.hub.save_hub_token") as mock_save:
            result = runner.invoke(app, ["hub", "login"], input="  token-with-spaces  \n")
        assert result.exit_code == 0
        mock_save.assert_called_once_with("token-with-spaces")


# ---------------------------------------------------------------------------
# hub logout
# ---------------------------------------------------------------------------


class TestHubLogout:
    def test_logout_removes_token(self):
        with patch("initrunner.hub.remove_hub_token") as mock_remove:
            result = runner.invoke(app, ["hub", "logout"])
        assert result.exit_code == 0
        assert "credentials removed" in result.output
        mock_remove.assert_called_once()


# ---------------------------------------------------------------------------
# hub whoami
# ---------------------------------------------------------------------------


class TestHubWhoami:
    def test_whoami_success(self):
        with (
            patch("initrunner.hub.load_hub_token", return_value="valid-token"),
            patch(
                "initrunner.hub._hub_request",
                return_value={"username": "alice"},
            ),
        ):
            result = runner.invoke(app, ["hub", "whoami"])
        assert result.exit_code == 0
        assert "alice" in result.output

    def test_whoami_not_logged_in(self):
        with patch("initrunner.hub.load_hub_token", return_value=None):
            result = runner.invoke(app, ["hub", "whoami"])
        assert result.exit_code == 1
        assert "Not logged in" in result.output

    def test_whoami_invalid_token(self):
        from initrunner.hub import HubAuthError

        with (
            patch("initrunner.hub.load_hub_token", return_value="bad-token"),
            patch(
                "initrunner.hub._hub_request",
                side_effect=HubAuthError("Authentication failed"),
            ),
        ):
            result = runner.invoke(app, ["hub", "whoami"])
        assert result.exit_code == 1
        assert "invalid or expired" in result.output

    def test_whoami_hub_error(self):
        with (
            patch("initrunner.hub.load_hub_token", return_value="token"),
            patch(
                "initrunner.hub._hub_request",
                side_effect=HubError("Connection error"),
            ),
        ):
            result = runner.invoke(app, ["hub", "whoami"])
        assert result.exit_code == 1
        assert "Connection error" in result.output


# ---------------------------------------------------------------------------
# hub search
# ---------------------------------------------------------------------------


class TestHubSearch:
    def test_search_with_results(self):
        results = [
            HubSearchResult(
                owner="alice",
                name="code-reviewer",
                description="Reviews code changes",
                tags=["code", "review"],
                downloads=42,
                latest_version="1.0.0",
            ),
        ]
        with patch("initrunner.hub.hub_search", return_value=results):
            result = runner.invoke(app, ["hub", "search", "code"])
        assert result.exit_code == 0
        assert "alice/code-review" in result.output
        assert "Reviews code" in result.output

    def test_search_no_results(self):
        with patch("initrunner.hub.hub_search", return_value=[]):
            result = runner.invoke(app, ["hub", "search", "nonexistent"])
        assert result.exit_code == 0
        assert "No packages found" in result.output

    def test_search_error(self):
        with patch("initrunner.hub.hub_search", side_effect=HubError("Network error")):
            result = runner.invoke(app, ["hub", "search", "query"])
        assert result.exit_code == 1
        assert "Network error" in result.output


# ---------------------------------------------------------------------------
# hub info
# ---------------------------------------------------------------------------


class TestHubInfo:
    def test_info_success(self):
        pkg = HubPackageInfo(
            owner="alice",
            name="code-reviewer",
            description="Reviews code",
            tags=["code"],
            latest_version="1.2.0",
            versions=["1.0.0", "1.1.0", "1.2.0"],
            downloads=100,
            author="Alice Smith",
            repository_url="https://github.com/alice/code-reviewer",
        )
        with patch("initrunner.hub.hub_resolve", return_value=pkg):
            result = runner.invoke(app, ["hub", "info", "alice/code-reviewer"])
        assert result.exit_code == 0
        assert "alice/code-reviewer" in result.output
        assert "Reviews code" in result.output
        assert "Alice Smith" in result.output
        assert "1.2.0" in result.output

    def test_info_no_slash(self):
        result = runner.invoke(app, ["hub", "info", "justname"])
        assert result.exit_code == 1
        assert "owner/name" in result.output

    def test_info_error(self):
        with patch("initrunner.hub.hub_resolve", side_effect=HubError("Not found")):
            result = runner.invoke(app, ["hub", "info", "alice/nonexistent"])
        assert result.exit_code == 1
        assert "Not found" in result.output


# ---------------------------------------------------------------------------
# hub publish
# ---------------------------------------------------------------------------


class TestHubPublish:
    def test_publish_success(self, tmp_path):
        role_file = tmp_path / "role.yaml"
        role_file.write_text("apiVersion: initrunner/v1\nkind: Agent\n")

        mock_bundle = tmp_path / "bundle.tar.gz"
        mock_bundle.write_bytes(b"fake-bundle")

        with (
            patch("initrunner.hub.load_hub_token", return_value="valid-token"),
            patch(
                "initrunner.packaging.bundle.create_bundle",
                return_value=mock_bundle,
            ),
            patch(
                "initrunner.hub.hub_publish",
                return_value={"owner": "alice", "name": "my-pack", "version": "1.0.0"},
            ),
        ):
            result = runner.invoke(app, ["hub", "publish", str(role_file)])
        assert result.exit_code == 0
        assert "Published" in result.output
        assert "alice/my-pack@1.0.0" in result.output

    def test_publish_not_logged_in(self, tmp_path):
        role_file = tmp_path / "role.yaml"
        role_file.write_text("content")

        with patch("initrunner.hub.load_hub_token", return_value=None):
            result = runner.invoke(app, ["hub", "publish", str(role_file)])
        assert result.exit_code == 1
        assert "Not logged in" in result.output

    def test_publish_file_not_found(self, tmp_path):
        with patch("initrunner.hub.load_hub_token", return_value="token"):
            result = runner.invoke(app, ["hub", "publish", str(tmp_path / "nonexistent.yaml")])
        assert result.exit_code == 1
        assert "File not found" in result.output

    def test_publish_bundle_error(self, tmp_path):
        role_file = tmp_path / "role.yaml"
        role_file.write_text("content")

        with (
            patch("initrunner.hub.load_hub_token", return_value="token"),
            patch(
                "initrunner.packaging.bundle.create_bundle",
                side_effect=RuntimeError("Bundle failed"),
            ),
        ):
            result = runner.invoke(app, ["hub", "publish", str(role_file)])
        assert result.exit_code == 1
        assert "Error creating bundle" in result.output

    def test_publish_hub_error(self, tmp_path):
        role_file = tmp_path / "role.yaml"
        role_file.write_text("content")

        mock_bundle = tmp_path / "bundle.tar.gz"
        mock_bundle.write_bytes(b"fake")

        with (
            patch("initrunner.hub.load_hub_token", return_value="token"),
            patch(
                "initrunner.packaging.bundle.create_bundle",
                return_value=mock_bundle,
            ),
            patch(
                "initrunner.hub.hub_publish",
                side_effect=HubError("Upload failed"),
            ),
        ):
            result = runner.invoke(app, ["hub", "publish", str(role_file)])
        assert result.exit_code == 1
        assert "Upload failed" in result.output
