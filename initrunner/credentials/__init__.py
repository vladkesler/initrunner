"""Credential resolution and vault storage.

The module splits reading from writing on purpose: runtime code asks a
``CredentialResolver`` for secrets, while only ``VaultStore`` implementations
mutate the encrypted vault. The default resolver checks ``os.environ`` first
and falls back to the local encrypted vault if one exists.
"""

from __future__ import annotations

from .resolver import (
    ChainedResolver,
    CredentialNotFound,
    CredentialResolver,
    EnvVarResolver,
    VaultResolver,
    get_resolver,
    require_credential,
    reset_resolver,
)
from .store import VaultLocked, VaultStore, WrongPassphrase

__all__ = [
    "ChainedResolver",
    "CredentialNotFound",
    "CredentialResolver",
    "EnvVarResolver",
    "VaultLocked",
    "VaultResolver",
    "VaultStore",
    "WrongPassphrase",
    "get_resolver",
    "require_credential",
    "reset_resolver",
]
