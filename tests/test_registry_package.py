"""Regression: registry package split preserves the exact public API surface."""

from pathlib import Path

import initrunner.registry as registry_pkg
from initrunner.registry._exceptions import RegistryError
from initrunner.registry._install import confirm_install
from initrunner.registry._manage import info_role, list_installed, uninstall_role
from initrunner.registry._manifest import load_manifest, save_manifest
from initrunner.registry._overrides import get_overrides_for_path, set_role_overrides
from initrunner.registry._preview import preview_install
from initrunner.registry._resolve import resolve_installed_path
from initrunner.registry._types import InstalledRole, InstallPreview, InstallResult, UpdateResult
from initrunner.registry._update import update_all, update_role

EXPECTED_PUBLIC_API = {
    # Exceptions
    "RegistryError",
    "RoleExistsError",
    "RoleNotFoundError",
    "NetworkError",
    # Dataclasses
    "InstallPreview",
    "InstallResult",
    "InstalledRole",
    "UpdateResult",
    # Constants
    "ROLES_DIR",
    "MANIFEST_PATH",
    # Manifest CRUD
    "load_manifest",
    "save_manifest",
    # Overrides
    "get_role_overrides",
    "set_role_overrides",
    "clear_role_overrides",
    "get_overrides_for_path",
    # Lifecycle
    "preview_install",
    "confirm_install",
    "install_role",
    "uninstall_role",
    "list_installed",
    "info_role",
    "resolve_installed_path",
    # Update
    "update_role",
    "update_all",
}


class TestRegistryPackageAPI:
    def test_all_matches_expected_surface(self) -> None:
        assert set(registry_pkg.__all__) == EXPECTED_PUBLIC_API

    def test_all_names_are_importable(self) -> None:
        for name in EXPECTED_PUBLIC_API:
            assert hasattr(registry_pkg, name), f"{name} in API but not importable"

    def test_re_exports_point_to_canonical_objects(self) -> None:
        """Verify re-exports are the same objects, not stale copies."""
        assert registry_pkg.RegistryError is RegistryError
        assert registry_pkg.load_manifest is load_manifest
        assert registry_pkg.save_manifest is save_manifest
        assert registry_pkg.confirm_install is confirm_install
        assert registry_pkg.preview_install is preview_install
        assert registry_pkg.uninstall_role is uninstall_role
        assert registry_pkg.list_installed is list_installed
        assert registry_pkg.info_role is info_role
        assert registry_pkg.resolve_installed_path is resolve_installed_path
        assert registry_pkg.set_role_overrides is set_role_overrides
        assert registry_pkg.get_overrides_for_path is get_overrides_for_path
        assert registry_pkg.update_role is update_role
        assert registry_pkg.update_all is update_all
        assert registry_pkg.InstallPreview is InstallPreview
        assert registry_pkg.InstallResult is InstallResult
        assert registry_pkg.InstalledRole is InstalledRole
        assert registry_pkg.UpdateResult is UpdateResult

    def test_roles_dir_is_path(self) -> None:
        assert isinstance(registry_pkg.ROLES_DIR, Path)

    def test_manifest_path_is_path(self) -> None:
        assert isinstance(registry_pkg.MANIFEST_PATH, Path)
