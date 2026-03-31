"""Registry exception hierarchy."""

from __future__ import annotations


class RegistryError(Exception):
    """Base error for registry operations."""


class RoleExistsError(RegistryError):
    """Role is already installed."""


class RoleNotFoundError(RegistryError):
    """Role not found in registry or on GitHub."""


class NetworkError(RegistryError):
    """Network request failed."""
