"""Tests for registry update operations."""

import json
from unittest.mock import patch

import pytest

from initrunner.registry import RoleNotFoundError, update_all, update_role


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

        monkeypatch.setattr("initrunner.registry._manifest.ROLES_DIR", roles_dir)
        monkeypatch.setattr("initrunner.registry._manifest.MANIFEST_PATH", manifest_path)

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
            patch("initrunner.registry._update._install_hub"),
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

        monkeypatch.setattr("initrunner.registry._manifest.ROLES_DIR", roles_dir)
        monkeypatch.setattr("initrunner.registry._manifest.MANIFEST_PATH", manifest_path)

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

        monkeypatch.setattr("initrunner.registry._manifest.ROLES_DIR", roles_dir)
        monkeypatch.setattr("initrunner.registry._manifest.MANIFEST_PATH", manifest_path)

        result = update_role("github:user/repo/test-agent")
        assert result.updated is False
        assert "no longer supported" in result.message
        assert "Reinstall from InitHub" in result.message

    def test_update_not_installed(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "initrunner.registry._manifest.MANIFEST_PATH", tmp_path / "registry.json"
        )
        with pytest.raises(RoleNotFoundError, match="not installed"):
            update_role("nonexistent")


class TestUpdateAll:
    def test_update_all_empty(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "initrunner.registry._manifest.MANIFEST_PATH", tmp_path / "registry.json"
        )
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

        monkeypatch.setattr("initrunner.registry._manifest.ROLES_DIR", roles_dir)
        monkeypatch.setattr("initrunner.registry._manifest.MANIFEST_PATH", manifest_path)

        from initrunner.hub import HubPackageInfo

        info = HubPackageInfo(owner="a", name="role-a", description="", latest_version="1.0.0")

        with patch("initrunner.hub.hub_resolve", return_value=info):
            results = update_all()

        assert len(results) == 2
