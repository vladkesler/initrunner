"""Tests for registry manifest CRUD."""

import json

from initrunner.registry import load_manifest, save_manifest


class TestManifest:
    def test_load_empty(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "initrunner.registry._manifest.MANIFEST_PATH", tmp_path / "registry.json"
        )
        data = load_manifest()
        assert data == {"roles": {}}

    def test_save_and_load(self, tmp_path, monkeypatch):
        manifest_path = tmp_path / "roles" / "registry.json"
        monkeypatch.setattr("initrunner.registry._manifest.MANIFEST_PATH", manifest_path)
        monkeypatch.setattr("initrunner.registry._manifest.ROLES_DIR", tmp_path / "roles")

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
        monkeypatch.setattr("initrunner.registry._manifest.MANIFEST_PATH", manifest_path)

        data = load_manifest()
        assert data == {"roles": {}}

    def test_load_missing_roles_key(self, tmp_path, monkeypatch):
        manifest_path = tmp_path / "registry.json"
        manifest_path.write_text("{}")
        monkeypatch.setattr("initrunner.registry._manifest.MANIFEST_PATH", manifest_path)

        data = load_manifest()
        assert "roles" in data

    def test_migrate_bare_name_keys(self, tmp_path, monkeypatch):
        """Legacy bare-name keys are migrated to qualified keys on load."""
        manifest_path = tmp_path / "registry.json"
        manifest_path.write_text(
            json.dumps(
                {
                    "roles": {
                        "test-agent": {
                            "source_type": "github",
                            "repo": "user/repo",
                            "local_path": "user__repo__test-agent.yaml",
                        }
                    }
                }
            )
        )
        monkeypatch.setattr("initrunner.registry._manifest.MANIFEST_PATH", manifest_path)

        data = load_manifest()
        assert "test-agent" not in data["roles"]
        assert "github:user/repo/test-agent" in data["roles"]
        assert data["roles"]["github:user/repo/test-agent"]["display_name"] == "test-agent"

    def test_migrate_oci_bare_name(self, tmp_path, monkeypatch):
        """Legacy OCI bare-name keys are migrated with oci: prefix."""
        manifest_path = tmp_path / "registry.json"
        manifest_path.write_text(
            json.dumps(
                {
                    "roles": {
                        "scanner": {
                            "source_type": "oci",
                            "oci_ref": "ghcr.io/org/scanner",
                            "local_path": "scanner",
                        }
                    }
                }
            )
        )
        monkeypatch.setattr("initrunner.registry._manifest.MANIFEST_PATH", manifest_path)

        data = load_manifest()
        assert "scanner" not in data["roles"]
        assert "oci:ghcr.io/org/scanner/scanner" in data["roles"]

    def test_qualified_keys_not_migrated(self, tmp_path, monkeypatch):
        """Already-qualified keys pass through unchanged."""
        manifest_path = tmp_path / "registry.json"
        original = {
            "roles": {
                "hub:alice/bot": {
                    "display_name": "bot",
                    "source_type": "hub",
                    "local_path": "hub__alice__bot",
                }
            }
        }
        manifest_path.write_text(json.dumps(original))
        monkeypatch.setattr("initrunner.registry._manifest.MANIFEST_PATH", manifest_path)

        data = load_manifest()
        assert data == original
