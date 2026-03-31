"""Tests for registry lifecycle management: uninstall, list, info."""

import json
import textwrap
from unittest.mock import patch

import pytest

from initrunner.registry import (
    RegistryError,
    RoleNotFoundError,
    info_role,
    list_installed,
    uninstall_role,
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

        monkeypatch.setattr("initrunner.registry._manifest.ROLES_DIR", roles_dir)
        monkeypatch.setattr("initrunner.registry._manifest.MANIFEST_PATH", manifest_path)

        uninstall_role("test-agent")

        assert not role_file.exists()
        manifest = json.loads(manifest_path.read_text())
        assert "test-agent" not in manifest["roles"]

    def test_uninstall_not_installed(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "initrunner.registry._manifest.MANIFEST_PATH", tmp_path / "registry.json"
        )
        with pytest.raises(RoleNotFoundError, match="not installed"):
            uninstall_role("nonexistent")


class TestListInstalled:
    def test_empty(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "initrunner.registry._manifest.MANIFEST_PATH", tmp_path / "registry.json"
        )
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

        monkeypatch.setattr("initrunner.registry._manifest.ROLES_DIR", roles_dir)
        monkeypatch.setattr("initrunner.registry._manifest.MANIFEST_PATH", manifest_path)

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

        monkeypatch.setattr("initrunner.registry._manifest.ROLES_DIR", roles_dir)
        monkeypatch.setattr("initrunner.registry._manifest.MANIFEST_PATH", manifest_path)

        roles = list_installed()
        assert len(roles) == 1
        assert roles[0].name == "my-agent"
        assert roles[0].repo == "alice/my-agent"
        assert roles[0].ref == "2.1.0"
        assert roles[0].hub_version == "2.1.0"
        assert roles[0].source_type == "hub"


class TestInfoRole:
    def test_info_hub_role(self, tmp_path, monkeypatch):
        """info_role returns metadata for hub sources."""
        from initrunner.hub import HubPackageInfo

        pkg = HubPackageInfo(
            owner="alice",
            name="scanner",
            description="Scans code",
            latest_version="1.2.0",
            versions=["1.0.0", "1.2.0"],
            downloads=42,
            tags=["security"],
        )

        with (
            patch("initrunner.hub.parse_hub_source", return_value=("alice", "scanner", None)),
            patch("initrunner.hub.hub_resolve", return_value=pkg),
        ):
            result = info_role("alice/scanner")

        assert result["name"] == "alice/scanner"
        assert result["source_type"] == "hub"
        assert result["latest_version"] == "1.2.0"
        assert result["downloads"] == 42

    def test_info_bare_name_raises(self):
        with pytest.raises(RegistryError, match="Search InitHub"):
            info_role("scanner")

    def test_info_deprecated_syntax_raises(self):
        with pytest.raises(RegistryError, match="no longer supported"):
            info_role("user/repo:path/role.yaml")
