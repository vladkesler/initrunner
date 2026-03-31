"""Tests for registry installed-role resolution."""

import json

import pytest

from initrunner.registry import RegistryError, resolve_installed_path


class TestResolveInstalledPath:
    """Tests for resolve_installed_path()."""

    def _setup_manifest(self, tmp_path, monkeypatch, roles_data, create_dirs=None):
        roles_dir = tmp_path / "roles"
        roles_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = roles_dir / "registry.json"
        manifest_path.write_text(json.dumps({"roles": roles_data}))
        monkeypatch.setattr("initrunner.registry._manifest.ROLES_DIR", roles_dir)
        monkeypatch.setattr("initrunner.registry._manifest.MANIFEST_PATH", manifest_path)
        for d in create_dirs or []:
            (roles_dir / d).mkdir(parents=True, exist_ok=True)
        return roles_dir

    def test_exact_qualified_key(self, tmp_path, monkeypatch):
        roles_dir = self._setup_manifest(
            tmp_path,
            monkeypatch,
            {
                "hub:alice/code-reviewer": {
                    "display_name": "code-reviewer",
                    "source_type": "hub",
                    "local_path": "hub__alice__code-reviewer",
                }
            },
            create_dirs=["hub__alice__code-reviewer"],
        )

        result = resolve_installed_path("hub:alice/code-reviewer")
        assert result == roles_dir / "hub__alice__code-reviewer"

    def test_owner_name_auto_prefix(self, tmp_path, monkeypatch):
        roles_dir = self._setup_manifest(
            tmp_path,
            monkeypatch,
            {
                "hub:alice/code-reviewer": {
                    "display_name": "code-reviewer",
                    "source_type": "hub",
                    "local_path": "hub__alice__code-reviewer",
                }
            },
            create_dirs=["hub__alice__code-reviewer"],
        )

        result = resolve_installed_path("alice/code-reviewer")
        assert result == roles_dir / "hub__alice__code-reviewer"

    def test_display_name_single_match(self, tmp_path, monkeypatch):
        roles_dir = self._setup_manifest(
            tmp_path,
            monkeypatch,
            {
                "hub:alice/code-reviewer": {
                    "display_name": "code-reviewer",
                    "source_type": "hub",
                    "local_path": "hub__alice__code-reviewer",
                }
            },
            create_dirs=["hub__alice__code-reviewer"],
        )

        result = resolve_installed_path("code-reviewer")
        assert result == roles_dir / "hub__alice__code-reviewer"

    def test_ambiguous_display_name_raises(self, tmp_path, monkeypatch):
        self._setup_manifest(
            tmp_path,
            monkeypatch,
            {
                "hub:alice/scanner": {
                    "display_name": "scanner",
                    "source_type": "hub",
                    "local_path": "hub__alice__scanner",
                },
                "oci:registry.io/repo/scanner": {
                    "display_name": "scanner",
                    "source_type": "oci",
                    "local_path": "oci__scanner",
                },
            },
            create_dirs=["hub__alice__scanner", "oci__scanner"],
        )

        with pytest.raises(RegistryError, match="Ambiguous"):
            resolve_installed_path("scanner")

    def test_missing_on_disk_returns_none(self, tmp_path, monkeypatch):
        self._setup_manifest(
            tmp_path,
            monkeypatch,
            {
                "hub:alice/gone": {
                    "display_name": "gone",
                    "source_type": "hub",
                    "local_path": "hub__alice__gone",
                }
            },
        )
        # Directory not created on disk
        result = resolve_installed_path("gone")
        assert result is None

    def test_no_match_returns_none(self, tmp_path, monkeypatch):
        self._setup_manifest(tmp_path, monkeypatch, {})
        result = resolve_installed_path("nonexistent")
        assert result is None
