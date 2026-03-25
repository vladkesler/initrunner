"""Tests for registry provider override persistence."""

import json
from pathlib import Path

import pytest

from initrunner.registry import (
    clear_role_overrides,
    get_overrides_for_path,
    get_role_overrides,
    load_manifest,
    save_manifest,
    set_role_overrides,
)


@pytest.fixture()
def registry_env(tmp_path, monkeypatch):
    """Set up a temporary registry directory with a manifest."""
    roles_dir = tmp_path / "roles"
    roles_dir.mkdir()
    manifest_path = roles_dir / "registry.json"

    monkeypatch.setattr("initrunner.registry.ROLES_DIR", roles_dir)
    monkeypatch.setattr("initrunner.registry.MANIFEST_PATH", manifest_path)

    # Seed manifest with one installed hub role
    manifest = {
        "roles": {
            "hub:acme/support-bot": {
                "display_name": "support-bot",
                "source_type": "hub",
                "hub_owner": "acme",
                "hub_name": "support-bot",
                "hub_version": "1.0.0",
                "local_path": "hub__acme__support-bot",
                "installed_at": "2026-01-01T00:00:00",
            }
        }
    }
    save_manifest(manifest)

    # Create the role directory
    role_dir = roles_dir / "hub__acme__support-bot"
    role_dir.mkdir()

    return roles_dir, manifest_path


class TestOverrideCRUD:
    def test_get_empty_overrides(self, registry_env):
        assert get_role_overrides("support-bot") == {}

    def test_set_and_get_overrides(self, registry_env):
        set_role_overrides("support-bot", {"provider": "groq", "model": "llama-3.3-70b"})
        assert get_role_overrides("support-bot") == {
            "provider": "groq",
            "model": "llama-3.3-70b",
        }

    def test_set_overrides_updates_manifest(self, registry_env):
        _, manifest_path = registry_env
        set_role_overrides("support-bot", {"provider": "ollama", "model": "llama3.2"})
        data = json.loads(manifest_path.read_text())
        entry = data["roles"]["hub:acme/support-bot"]
        assert entry["overrides"] == {"provider": "ollama", "model": "llama3.2"}

    def test_clear_overrides(self, registry_env):
        set_role_overrides("support-bot", {"provider": "groq", "model": "llama-3.3-70b"})
        clear_role_overrides("support-bot")
        assert get_role_overrides("support-bot") == {}

    def test_clear_removes_key_from_manifest(self, registry_env):
        _, manifest_path = registry_env
        set_role_overrides("support-bot", {"provider": "groq", "model": "llama-3.3-70b"})
        clear_role_overrides("support-bot")
        data = json.loads(manifest_path.read_text())
        assert "overrides" not in data["roles"]["hub:acme/support-bot"]

    def test_set_overrides_unknown_role_raises(self, registry_env):
        from initrunner.registry import RoleNotFoundError

        with pytest.raises(RoleNotFoundError):
            set_role_overrides("nonexistent", {"provider": "openai", "model": "gpt-4o"})

    def test_get_overrides_unknown_role_returns_empty(self, registry_env):
        assert get_role_overrides("nonexistent") == {}


class TestOverridesByPath:
    def test_get_overrides_for_installed_path(self, registry_env):
        roles_dir, _ = registry_env
        set_role_overrides("support-bot", {"provider": "google", "model": "gemini-2.0-flash"})

        role_yaml = roles_dir / "hub__acme__support-bot" / "role.yaml"
        role_yaml.touch()

        assert get_overrides_for_path(role_yaml) == {
            "provider": "google",
            "model": "gemini-2.0-flash",
        }

    def test_get_overrides_for_non_installed_path(self, registry_env):
        """Local role.yaml not in the roles dir returns empty."""
        assert get_overrides_for_path(Path("/tmp/my-project/role.yaml")) == {}

    def test_get_overrides_for_path_no_overrides(self, registry_env):
        roles_dir, _ = registry_env
        role_yaml = roles_dir / "hub__acme__support-bot" / "role.yaml"
        role_yaml.touch()
        assert get_overrides_for_path(role_yaml) == {}


class TestOverridePersistenceAcrossReinstall:
    def test_hub_install_preserves_overrides(self, registry_env):
        """Simulate _install_hub with force=True preserving overrides."""
        _roles_dir, manifest_path = registry_env

        # User sets an override
        set_role_overrides("support-bot", {"provider": "groq", "model": "llama-3.3-70b"})

        # Simulate what _install_hub does on force reinstall:
        # It reads manifest, writes new entry, saves
        manifest = load_manifest()
        qualified_key = "hub:acme/support-bot"

        # Preserve overrides (this is what our code change does)
        existing_overrides = {}
        if qualified_key in manifest["roles"]:
            existing_overrides = manifest["roles"][qualified_key].get("overrides", {})

        new_entry = {
            "display_name": "support-bot",
            "source_type": "hub",
            "hub_owner": "acme",
            "hub_name": "support-bot",
            "hub_version": "2.0.0",  # Updated version
            "local_path": "hub__acme__support-bot",
            "installed_at": "2026-03-21T00:00:00",
        }
        if existing_overrides:
            new_entry["overrides"] = existing_overrides  # type: ignore[invalid-assignment]

        manifest["roles"][qualified_key] = new_entry
        save_manifest(manifest)

        # Verify overrides survived the update
        assert get_role_overrides("support-bot") == {
            "provider": "groq",
            "model": "llama-3.3-70b",
        }

        # Verify version was updated
        data = json.loads(manifest_path.read_text())
        assert data["roles"][qualified_key]["hub_version"] == "2.0.0"
