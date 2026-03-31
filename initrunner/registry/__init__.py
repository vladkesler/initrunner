"""Role registry: install, uninstall, search, and manage community roles."""

from initrunner.registry._exceptions import (
    NetworkError,
    RegistryError,
    RoleExistsError,
    RoleNotFoundError,
)
from initrunner.registry._install import confirm_install, install_role
from initrunner.registry._manage import info_role, list_installed, uninstall_role
from initrunner.registry._manifest import (
    MANIFEST_PATH,
    ROLES_DIR,
    load_manifest,
    save_manifest,
)
from initrunner.registry._overrides import (
    clear_role_overrides,
    get_overrides_for_path,
    get_role_overrides,
    set_role_overrides,
)
from initrunner.registry._preview import preview_install
from initrunner.registry._resolve import resolve_installed_path
from initrunner.registry._types import (
    InstalledRole,
    InstallPreview,
    InstallResult,
    UpdateResult,
)
from initrunner.registry._update import update_all, update_role

__all__ = [
    "MANIFEST_PATH",
    "ROLES_DIR",
    "InstallPreview",
    "InstallResult",
    "InstalledRole",
    "NetworkError",
    "RegistryError",
    "RoleExistsError",
    "RoleNotFoundError",
    "UpdateResult",
    "clear_role_overrides",
    "confirm_install",
    "get_overrides_for_path",
    "get_role_overrides",
    "info_role",
    "install_role",
    "list_installed",
    "load_manifest",
    "preview_install",
    "resolve_installed_path",
    "save_manifest",
    "set_role_overrides",
    "uninstall_role",
    "update_all",
    "update_role",
]
