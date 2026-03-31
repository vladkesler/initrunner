"""Tests for registry install flow."""

import json
import textwrap
from unittest.mock import MagicMock, patch

import pytest

from initrunner.registry import (
    InstallResult,
    RegistryError,
    RoleExistsError,
    confirm_install,
    install_role,
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
        roles_dir = tmp_path / "roles"
        monkeypatch.setattr("initrunner.registry._manifest.ROLES_DIR", roles_dir)
        monkeypatch.setattr(
            "initrunner.registry._manifest.MANIFEST_PATH", roles_dir / "registry.json"
        )

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
            result = confirm_install("user/test-agent")

        assert isinstance(result, InstallResult)
        assert result.path == target_dir
        assert result.display_name == "test-agent"
        manifest = json.loads((roles_dir / "registry.json").read_text())
        assert "hub:user/test-agent" in manifest["roles"]
        entry = manifest["roles"]["hub:user/test-agent"]
        assert entry["source_type"] == "hub"
        assert entry["hub_owner"] == "user"
        assert entry["hub_name"] == "test-agent"

    def test_hub_prefix_routes_to_hub(self, tmp_path, monkeypatch):
        """hub:owner/name format still routes to InitHub."""
        roles_dir = tmp_path / "roles"
        monkeypatch.setattr("initrunner.registry._manifest.ROLES_DIR", roles_dir)
        monkeypatch.setattr(
            "initrunner.registry._manifest.MANIFEST_PATH", roles_dir / "registry.json"
        )

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
            result = confirm_install("hub:user/test-agent")

        assert result.path == target_dir

    def test_bare_name_raises_helpful_error(self, tmp_path, monkeypatch):
        """Bare name like 'code-reviewer' raises error with search hint."""
        roles_dir = tmp_path / "roles"
        monkeypatch.setattr("initrunner.registry._manifest.ROLES_DIR", roles_dir)

        with pytest.raises(RegistryError, match="Search InitHub"):
            confirm_install("code-reviewer")

    def test_github_path_syntax_raises_error(self, tmp_path, monkeypatch):
        """owner/repo:path syntax raises error about deprecated syntax."""
        roles_dir = tmp_path / "roles"
        monkeypatch.setattr("initrunner.registry._manifest.ROLES_DIR", roles_dir)

        with pytest.raises(RegistryError, match="no longer supported"):
            confirm_install("user/repo:path/role.yaml")

    def test_install_collision_without_force(self, tmp_path, monkeypatch):
        roles_dir = tmp_path / "roles"
        target_dir = roles_dir / "hub__user__test-agent"
        target_dir.mkdir(parents=True)
        monkeypatch.setattr("initrunner.registry._manifest.ROLES_DIR", roles_dir)
        monkeypatch.setattr(
            "initrunner.registry._manifest.MANIFEST_PATH", roles_dir / "registry.json"
        )

        info = self._mock_hub_info()
        with (
            patch("initrunner.hub.parse_hub_source", return_value=("user", "test-agent", None)),
            patch("initrunner.hub.hub_resolve", return_value=info),
        ):
            with pytest.raises(RoleExistsError, match="already installed"):
                confirm_install("user/test-agent")

    def test_install_network_error(self, tmp_path, monkeypatch):
        roles_dir = tmp_path / "roles"
        monkeypatch.setattr("initrunner.registry._manifest.ROLES_DIR", roles_dir)

        from initrunner.hub import HubError

        with (
            patch("initrunner.hub.parse_hub_source", return_value=("user", "test-agent", None)),
            patch("initrunner.hub.hub_resolve", side_effect=HubError("Connection failed")),
        ):
            with pytest.raises(HubError):
                confirm_install("user/test-agent")

    def test_install_role_convenience_wrapper(self, tmp_path, monkeypatch):
        """install_role() delegates to confirm_install()."""
        roles_dir = tmp_path / "roles"
        monkeypatch.setattr("initrunner.registry._manifest.ROLES_DIR", roles_dir)
        monkeypatch.setattr(
            "initrunner.registry._manifest.MANIFEST_PATH", roles_dir / "registry.json"
        )

        info = self._mock_hub_info()

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
            result = install_role("user/test-agent")

        assert isinstance(result, InstallResult)
        assert result.display_name == "test-agent"
