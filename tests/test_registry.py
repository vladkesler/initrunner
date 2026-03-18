"""Tests for the role registry."""

import json
import textwrap
from unittest.mock import patch

import pytest

from initrunner.registry import (
    RegistryError,
    RoleExistsError,
    RoleNotFoundError,
    confirm_install,
    list_installed,
    load_manifest,
    save_manifest,
    uninstall_role,
    update_all,
    update_role,
)

VALID_ROLE_YAML = textwrap.dedent("""\
    apiVersion: initrunner/v1
    kind: Agent
    metadata:
      name: test-agent
      description: A test agent
      author: testuser
      version: "1.0.0"
      dependencies: []
    spec:
      role: You are helpful.
      model:
        provider: openai
        name: gpt-5-mini
""")


# ---------------------------------------------------------------------------
# Manifest CRUD
# ---------------------------------------------------------------------------


class TestManifest:
    def test_load_empty(self, tmp_path, monkeypatch):
        monkeypatch.setattr("initrunner.registry.MANIFEST_PATH", tmp_path / "registry.json")
        data = load_manifest()
        assert data == {"roles": {}}

    def test_save_and_load(self, tmp_path, monkeypatch):
        manifest_path = tmp_path / "roles" / "registry.json"
        monkeypatch.setattr("initrunner.registry.MANIFEST_PATH", manifest_path)
        monkeypatch.setattr("initrunner.registry.ROLES_DIR", tmp_path / "roles")

        data = {
            "roles": {
                "github:user/repo/test": {
                    "source_url": "https://example.com",
                    "ref": "main",
                    "display_name": "test",
                    "source_type": "github",
                    "repo": "user/repo",
                }
            }
        }
        save_manifest(data)

        loaded = load_manifest()
        assert loaded == data

    def test_load_corrupt_json(self, tmp_path, monkeypatch):
        manifest_path = tmp_path / "registry.json"
        manifest_path.write_text("not json{{{")
        monkeypatch.setattr("initrunner.registry.MANIFEST_PATH", manifest_path)

        data = load_manifest()
        assert data == {"roles": {}}

    def test_load_missing_roles_key(self, tmp_path, monkeypatch):
        manifest_path = tmp_path / "registry.json"
        manifest_path.write_text("{}")
        monkeypatch.setattr("initrunner.registry.MANIFEST_PATH", manifest_path)

        data = load_manifest()
        assert "roles" in data


# ---------------------------------------------------------------------------
# Install flow (InitHub routing)
# ---------------------------------------------------------------------------


class TestInstallRole:
    def _mock_hub_info(self, owner="user", name="test-agent", version="1.0.0"):
        from initrunner.hub import HubPackageInfo

        return HubPackageInfo(
            owner=owner,
            name=name,
            description="A test agent",
            latest_version=version,
            versions=[version],
            downloads=10,
        )

    def test_owner_name_routes_to_hub(self, tmp_path, monkeypatch):
        """owner/name format (no hub: prefix) routes to InitHub."""
        from unittest.mock import MagicMock

        roles_dir = tmp_path / "roles"
        monkeypatch.setattr("initrunner.registry.ROLES_DIR", roles_dir)
        monkeypatch.setattr("initrunner.registry.MANIFEST_PATH", roles_dir / "registry.json")

        info = self._mock_hub_info()
        target_dir = roles_dir / "hub__user__test-agent"

        def fake_extract(archive, dest):
            dest.mkdir(parents=True, exist_ok=True)
            m = MagicMock()
            m.name = "test-agent"
            return m

        with (
            patch("initrunner.hub.parse_hub_source", return_value=("user", "test-agent", None)),
            patch("initrunner.hub.hub_resolve", return_value=info),
            patch("initrunner.hub.hub_download", return_value=b"fake-bundle"),
            patch("initrunner.packaging.bundle.extract_bundle", side_effect=fake_extract),
        ):
            path = confirm_install("user/test-agent")

        assert path == target_dir
        manifest = json.loads((roles_dir / "registry.json").read_text())
        assert "hub:user/test-agent" in manifest["roles"]
        entry = manifest["roles"]["hub:user/test-agent"]
        assert entry["source_type"] == "hub"
        assert entry["hub_owner"] == "user"
        assert entry["hub_name"] == "test-agent"

    def test_hub_prefix_routes_to_hub(self, tmp_path, monkeypatch):
        """hub:owner/name format still routes to InitHub."""
        from unittest.mock import MagicMock

        roles_dir = tmp_path / "roles"
        monkeypatch.setattr("initrunner.registry.ROLES_DIR", roles_dir)
        monkeypatch.setattr("initrunner.registry.MANIFEST_PATH", roles_dir / "registry.json")

        info = self._mock_hub_info()
        target_dir = roles_dir / "hub__user__test-agent"

        def fake_extract(archive, dest):
            dest.mkdir(parents=True, exist_ok=True)
            m = MagicMock()
            m.name = "test-agent"
            return m

        with (
            patch("initrunner.hub.parse_hub_source", return_value=("user", "test-agent", None)),
            patch("initrunner.hub.hub_resolve", return_value=info),
            patch("initrunner.hub.hub_download", return_value=b"fake-bundle"),
            patch("initrunner.packaging.bundle.extract_bundle", side_effect=fake_extract),
        ):
            path = confirm_install("hub:user/test-agent")

        assert path == target_dir

    def test_bare_name_raises_helpful_error(self, tmp_path, monkeypatch):
        """Bare name like 'code-reviewer' raises error with search hint."""
        roles_dir = tmp_path / "roles"
        monkeypatch.setattr("initrunner.registry.ROLES_DIR", roles_dir)

        with pytest.raises(RegistryError, match="Search InitHub"):
            confirm_install("code-reviewer")

    def test_github_path_syntax_raises_error(self, tmp_path, monkeypatch):
        """owner/repo:path syntax raises error about deprecated syntax."""
        roles_dir = tmp_path / "roles"
        monkeypatch.setattr("initrunner.registry.ROLES_DIR", roles_dir)

        with pytest.raises(RegistryError, match="no longer supported"):
            confirm_install("user/repo:path/role.yaml")

    def test_install_collision_without_force(self, tmp_path, monkeypatch):
        roles_dir = tmp_path / "roles"
        target_dir = roles_dir / "hub__user__test-agent"
        target_dir.mkdir(parents=True)
        monkeypatch.setattr("initrunner.registry.ROLES_DIR", roles_dir)
        monkeypatch.setattr("initrunner.registry.MANIFEST_PATH", roles_dir / "registry.json")

        info = self._mock_hub_info()
        with (
            patch("initrunner.hub.parse_hub_source", return_value=("user", "test-agent", None)),
            patch("initrunner.hub.hub_resolve", return_value=info),
        ):
            with pytest.raises(RoleExistsError, match="already installed"):
                confirm_install("user/test-agent")

    def test_install_network_error(self, tmp_path, monkeypatch):
        roles_dir = tmp_path / "roles"
        monkeypatch.setattr("initrunner.registry.ROLES_DIR", roles_dir)

        from initrunner.hub import HubError

        with (
            patch("initrunner.hub.parse_hub_source", return_value=("user", "test-agent", None)),
            patch("initrunner.hub.hub_resolve", side_effect=HubError("Connection failed")),
        ):
            with pytest.raises(HubError):
                confirm_install("user/test-agent")


# ---------------------------------------------------------------------------
# Uninstall
# ---------------------------------------------------------------------------


class TestUninstallRole:
    def test_uninstall_success(self, tmp_path, monkeypatch):
        roles_dir = tmp_path / "roles"
        roles_dir.mkdir(parents=True)
        role_file = roles_dir / "user__repo__test-agent.yaml"
        role_file.write_text(VALID_ROLE_YAML)

        manifest_path = roles_dir / "registry.json"
        manifest_path.write_text(
            json.dumps(
                {
                    "roles": {
                        "test-agent": {
                            "local_path": "user__repo__test-agent.yaml",
                            "repo": "user/repo",
                        }
                    }
                }
            )
        )

        monkeypatch.setattr("initrunner.registry.ROLES_DIR", roles_dir)
        monkeypatch.setattr("initrunner.registry.MANIFEST_PATH", manifest_path)

        uninstall_role("test-agent")

        assert not role_file.exists()
        manifest = json.loads(manifest_path.read_text())
        assert "test-agent" not in manifest["roles"]

    def test_uninstall_not_installed(self, tmp_path, monkeypatch):
        monkeypatch.setattr("initrunner.registry.MANIFEST_PATH", tmp_path / "registry.json")
        with pytest.raises(RoleNotFoundError, match="not installed"):
            uninstall_role("nonexistent")


# ---------------------------------------------------------------------------
# List installed
# ---------------------------------------------------------------------------


class TestListInstalled:
    def test_empty(self, tmp_path, monkeypatch):
        monkeypatch.setattr("initrunner.registry.MANIFEST_PATH", tmp_path / "registry.json")
        assert list_installed() == []

    def test_with_roles(self, tmp_path, monkeypatch):
        roles_dir = tmp_path / "roles"
        roles_dir.mkdir()
        manifest_path = roles_dir / "registry.json"
        manifest_path.write_text(
            json.dumps(
                {
                    "roles": {
                        "test-agent": {
                            "source_url": "https://example.com",
                            "repo": "user/repo",
                            "ref": "main",
                            "local_path": "user__repo__test-agent.yaml",
                            "installed_at": "2026-02-10T12:00:00",
                        }
                    }
                }
            )
        )

        monkeypatch.setattr("initrunner.registry.ROLES_DIR", roles_dir)
        monkeypatch.setattr("initrunner.registry.MANIFEST_PATH", manifest_path)

        roles = list_installed()
        assert len(roles) == 1
        assert roles[0].name == "test-agent"
        assert roles[0].repo == "user/repo"

    def test_hub_list_shows_owner_name_and_version(self, tmp_path, monkeypatch):
        """Hub entries display owner/name as repo and version as ref."""
        roles_dir = tmp_path / "roles"
        roles_dir.mkdir()
        manifest_path = roles_dir / "registry.json"
        manifest_path.write_text(
            json.dumps(
                {
                    "roles": {
                        "hub:alice/my-agent": {
                            "display_name": "my-agent",
                            "source_type": "hub",
                            "hub_owner": "alice",
                            "hub_name": "my-agent",
                            "hub_version": "2.1.0",
                            "local_path": "hub__alice__my-agent",
                            "installed_at": "2026-03-18T12:00:00",
                        }
                    }
                }
            )
        )

        monkeypatch.setattr("initrunner.registry.ROLES_DIR", roles_dir)
        monkeypatch.setattr("initrunner.registry.MANIFEST_PATH", manifest_path)

        roles = list_installed()
        assert len(roles) == 1
        assert roles[0].name == "my-agent"
        assert roles[0].repo == "alice/my-agent"
        assert roles[0].ref == "2.1.0"
        assert roles[0].hub_version == "2.1.0"
        assert roles[0].source_type == "hub"


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------


class TestUpdateRole:
    def test_update_hub_role(self, tmp_path, monkeypatch):
        roles_dir = tmp_path / "roles"
        roles_dir.mkdir(parents=True)

        manifest_path = roles_dir / "registry.json"
        manifest_path.write_text(
            json.dumps(
                {
                    "roles": {
                        "hub:user/test-agent": {
                            "display_name": "test-agent",
                            "source_type": "hub",
                            "hub_owner": "user",
                            "hub_name": "test-agent",
                            "hub_version": "1.0.0",
                            "local_path": "hub__user__test-agent",
                            "installed_at": "2026-03-01T00:00:00",
                        }
                    }
                }
            )
        )

        monkeypatch.setattr("initrunner.registry.ROLES_DIR", roles_dir)
        monkeypatch.setattr("initrunner.registry.MANIFEST_PATH", manifest_path)

        from initrunner.hub import HubPackageInfo

        new_info = HubPackageInfo(
            owner="user",
            name="test-agent",
            description="Updated",
            latest_version="2.0.0",
            versions=["1.0.0", "2.0.0"],
        )

        with (
            patch("initrunner.hub.hub_resolve", return_value=new_info),
            patch("initrunner.registry._install_hub"),
        ):
            result = update_role("hub:user/test-agent")

        assert result.updated is True
        assert result.new_sha == "2.0.0"
        assert "Updated to 2.0.0" in result.message

    def test_update_hub_role_up_to_date(self, tmp_path, monkeypatch):
        roles_dir = tmp_path / "roles"
        roles_dir.mkdir(parents=True)

        manifest_path = roles_dir / "registry.json"
        manifest_path.write_text(
            json.dumps(
                {
                    "roles": {
                        "hub:user/test-agent": {
                            "display_name": "test-agent",
                            "source_type": "hub",
                            "hub_owner": "user",
                            "hub_name": "test-agent",
                            "hub_version": "1.0.0",
                            "local_path": "hub__user__test-agent",
                        }
                    }
                }
            )
        )

        monkeypatch.setattr("initrunner.registry.ROLES_DIR", roles_dir)
        monkeypatch.setattr("initrunner.registry.MANIFEST_PATH", manifest_path)

        from initrunner.hub import HubPackageInfo

        info = HubPackageInfo(
            owner="user", name="test-agent", description="Same", latest_version="1.0.0"
        )

        with patch("initrunner.hub.hub_resolve", return_value=info):
            result = update_role("hub:user/test-agent")

        assert result.updated is False
        assert "up to date" in result.message

    def test_legacy_github_entry_returns_unsupported(self, tmp_path, monkeypatch):
        """Legacy GitHub manifest entries return 'no longer supported' message."""
        roles_dir = tmp_path / "roles"
        roles_dir.mkdir(parents=True)
        manifest_path = roles_dir / "registry.json"
        manifest_path.write_text(
            json.dumps(
                {
                    "roles": {
                        "github:user/repo/test-agent": {
                            "display_name": "test-agent",
                            "source_type": "github",
                            "source_url": "https://raw.githubusercontent.com/user/repo/main/role.yaml",
                            "repo": "user/repo",
                            "ref": "main",
                            "commit_sha": "abc123",
                            "local_path": "user__repo__test-agent.yaml",
                        }
                    }
                }
            )
        )

        monkeypatch.setattr("initrunner.registry.ROLES_DIR", roles_dir)
        monkeypatch.setattr("initrunner.registry.MANIFEST_PATH", manifest_path)

        result = update_role("github:user/repo/test-agent")
        assert result.updated is False
        assert "no longer supported" in result.message
        assert "Reinstall from InitHub" in result.message

    def test_update_not_installed(self, tmp_path, monkeypatch):
        monkeypatch.setattr("initrunner.registry.MANIFEST_PATH", tmp_path / "registry.json")
        with pytest.raises(RoleNotFoundError, match="not installed"):
            update_role("nonexistent")


class TestUpdateAll:
    def test_update_all_empty(self, tmp_path, monkeypatch):
        monkeypatch.setattr("initrunner.registry.MANIFEST_PATH", tmp_path / "registry.json")
        results = update_all()
        assert results == []

    def test_update_all_multiple(self, tmp_path, monkeypatch):
        roles_dir = tmp_path / "roles"
        roles_dir.mkdir(parents=True)

        manifest_path = roles_dir / "registry.json"
        manifest_path.write_text(
            json.dumps(
                {
                    "roles": {
                        "hub:a/role-a": {
                            "display_name": "role-a",
                            "source_type": "hub",
                            "hub_owner": "a",
                            "hub_name": "role-a",
                            "hub_version": "1.0.0",
                            "local_path": "hub__a__role-a",
                        },
                        "hub:b/role-b": {
                            "display_name": "role-b",
                            "source_type": "hub",
                            "hub_owner": "b",
                            "hub_name": "role-b",
                            "hub_version": "1.0.0",
                            "local_path": "hub__b__role-b",
                        },
                    }
                }
            )
        )

        monkeypatch.setattr("initrunner.registry.ROLES_DIR", roles_dir)
        monkeypatch.setattr("initrunner.registry.MANIFEST_PATH", manifest_path)

        from initrunner.hub import HubPackageInfo

        info = HubPackageInfo(owner="a", name="role-a", description="", latest_version="1.0.0")

        with patch("initrunner.hub.hub_resolve", return_value=info):
            results = update_all()

        assert len(results) == 2


# ---------------------------------------------------------------------------
# CLI commands
# ---------------------------------------------------------------------------


class TestCLIInstall:
    def test_install_owner_name_routes_to_hub(self, tmp_path, monkeypatch):
        from typer.testing import CliRunner

        from initrunner.cli.main import app

        runner = CliRunner()
        roles_dir = tmp_path / "roles"
        monkeypatch.setattr("initrunner.registry.ROLES_DIR", roles_dir)
        monkeypatch.setattr("initrunner.registry.MANIFEST_PATH", roles_dir / "registry.json")

        from initrunner.hub import HubPackageInfo

        info = HubPackageInfo(
            owner="user",
            name="test-agent",
            description="Test",
            latest_version="1.0.0",
            versions=["1.0.0"],
        )

        def fake_extract(archive, dest):
            dest.mkdir(parents=True, exist_ok=True)
            from unittest.mock import MagicMock

            m = MagicMock()
            m.name = "test-agent"
            return m

        with (
            patch("initrunner.hub.parse_hub_source", return_value=("user", "test-agent", None)),
            patch("initrunner.hub.hub_resolve", return_value=info),
            patch("initrunner.hub.hub_download", return_value=b"fake-bundle"),
            patch("initrunner.packaging.bundle.extract_bundle", side_effect=fake_extract),
        ):
            result = runner.invoke(app, ["install", "user/test-agent", "--yes"])

        assert result.exit_code == 0
        assert "Installed" in result.output

    def test_install_bare_name_shows_error(self, tmp_path, monkeypatch):
        from typer.testing import CliRunner

        from initrunner.cli.main import app

        runner = CliRunner()

        result = runner.invoke(app, ["install", "code-reviewer", "--yes"])

        assert result.exit_code == 1
        assert "Search InitHub" in result.output

    def test_install_not_found(self, tmp_path, monkeypatch):
        from typer.testing import CliRunner

        from initrunner.cli.main import app

        runner = CliRunner()

        from initrunner.hub import HubError

        with (
            patch("initrunner.hub.parse_hub_source", return_value=("user", "nonexistent", None)),
            patch(
                "initrunner.hub.hub_resolve",
                side_effect=HubError("Not found: /packages/user/nonexistent"),
            ),
        ):
            result = runner.invoke(app, ["install", "user/nonexistent", "--yes"])

        assert result.exit_code == 1
        assert "Not found" in result.output


class TestCLIUninstall:
    def test_uninstall_command(self, tmp_path, monkeypatch):
        from typer.testing import CliRunner

        from initrunner.cli.main import app

        runner = CliRunner()
        roles_dir = tmp_path / "roles"
        roles_dir.mkdir(parents=True)
        (roles_dir / "user__repo__test-agent.yaml").write_text(VALID_ROLE_YAML)
        manifest_path = roles_dir / "registry.json"
        manifest_path.write_text(
            json.dumps(
                {
                    "roles": {
                        "test-agent": {
                            "local_path": "user__repo__test-agent.yaml",
                            "repo": "user/repo",
                        }
                    }
                }
            )
        )

        monkeypatch.setattr("initrunner.registry.ROLES_DIR", roles_dir)
        monkeypatch.setattr("initrunner.registry.MANIFEST_PATH", manifest_path)

        result = runner.invoke(app, ["uninstall", "test-agent"])
        assert result.exit_code == 0
        assert "Uninstalled" in result.output

    def test_uninstall_not_installed(self, tmp_path, monkeypatch):
        from typer.testing import CliRunner

        from initrunner.cli.main import app

        runner = CliRunner()
        monkeypatch.setattr("initrunner.registry.MANIFEST_PATH", tmp_path / "registry.json")

        result = runner.invoke(app, ["uninstall", "nonexistent"])
        assert result.exit_code == 1


class TestCLIList:
    def test_list_empty(self, tmp_path, monkeypatch):
        from typer.testing import CliRunner

        from initrunner.cli.main import app

        runner = CliRunner()
        monkeypatch.setattr("initrunner.registry.MANIFEST_PATH", tmp_path / "registry.json")

        result = runner.invoke(app, ["list"])
        assert result.exit_code == 0
        assert "No roles installed" in result.output

    def test_list_with_roles(self, tmp_path, monkeypatch):
        from typer.testing import CliRunner

        from initrunner.cli.main import app

        runner = CliRunner()
        roles_dir = tmp_path / "roles"
        roles_dir.mkdir()
        manifest_path = roles_dir / "registry.json"
        manifest_path.write_text(
            json.dumps(
                {
                    "roles": {
                        "test-agent": {
                            "source_url": "https://example.com",
                            "repo": "user/repo",
                            "ref": "main",
                            "local_path": "user__repo__test-agent.yaml",
                            "installed_at": "2026-02-10T12:00:00",
                        }
                    }
                }
            )
        )

        monkeypatch.setattr("initrunner.registry.ROLES_DIR", roles_dir)
        monkeypatch.setattr("initrunner.registry.MANIFEST_PATH", manifest_path)

        result = runner.invoke(app, ["list"])
        assert result.exit_code == 0
        assert "test-agent" in result.output


class TestCLISearch:
    def test_search_command(self):
        from typer.testing import CliRunner

        from initrunner.cli.main import app
        from initrunner.hub import HubSearchResult

        runner = CliRunner()
        hub_results = [
            HubSearchResult(
                owner="test",
                name="code-reviewer",
                description="Reviews code",
                tags=["code"],
                downloads=10,
                latest_version="1.0.0",
            )
        ]
        with patch("initrunner.hub.hub_search", return_value=hub_results):
            result = runner.invoke(app, ["search", "code"])

        assert result.exit_code == 0
        assert "code-reviewer" in result.output

    def test_search_no_results(self):
        from typer.testing import CliRunner

        from initrunner.cli.main import app

        runner = CliRunner()
        with patch("initrunner.hub.hub_search", return_value=[]):
            result = runner.invoke(app, ["search", "nonexistent"])

        assert result.exit_code == 0
        assert "No packages found" in result.output


class TestCLIUpdate:
    def test_update_all_command(self, tmp_path, monkeypatch):
        from typer.testing import CliRunner

        from initrunner.cli.main import app

        runner = CliRunner()
        monkeypatch.setattr("initrunner.registry.MANIFEST_PATH", tmp_path / "registry.json")

        result = runner.invoke(app, ["update"])
        assert result.exit_code == 0
        assert "No roles installed" in result.output
