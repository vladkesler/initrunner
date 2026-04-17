"""Credential resolver: read-only ``get(name)`` over env + vault.

The resolver is deliberately read-only; writes go through ``VaultStore``.
The default instance is a ``ChainedResolver`` that checks ``os.environ``
first and falls back to the local encrypted vault when one exists. Env
always wins so CI, Docker ``-e``, and shell exports keep working
identically.
"""

from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod

from ..config import get_vault_path
from . import passphrase
from .local_vault import LocalEncryptedVault
from .store import VaultLocked, VaultStore, WrongPassphrase

_logger = logging.getLogger(__name__)


class CredentialNotFound(RuntimeError):
    """Raised by ``require_credential`` when a mandatory secret is missing."""


class CredentialResolver(ABC):
    @abstractmethod
    def get(self, name: str) -> str | None: ...


class EnvVarResolver(CredentialResolver):
    def get(self, name: str) -> str | None:
        value = os.environ.get(name)
        return value if value else None


class VaultResolver(CredentialResolver):
    """Wraps a ``VaultStore`` with a non-interactive unlock path.

    If the vault is locked and a passphrase is available from
    ``INITRUNNER_VAULT_PASSPHRASE`` or the keyring cache, it unlocks
    transparently. Otherwise ``get`` returns ``None`` — it never prompts.
    The same instance is reused across resolutions so scrypt runs once.
    """

    def __init__(self, store: VaultStore) -> None:
        self._store = store
        self._unlock_attempted = False

    @property
    def store(self) -> VaultStore:
        return self._store

    def get(self, name: str) -> str | None:
        if not self._store.exists():
            return None
        if not self._store.is_unlocked():
            if not self._try_unlock_non_interactive():
                return None
        try:
            return self._store.get(name)
        except VaultLocked:
            return None

    def _try_unlock_non_interactive(self) -> bool:
        if self._unlock_attempted:
            return self._store.is_unlocked()
        self._unlock_attempted = True
        pw = passphrase.acquire(interactive=False)
        if pw is None:
            return False
        try:
            self._store.unlock(pw)
            return True
        except WrongPassphrase:
            _logger.warning("vault passphrase from env/keyring rejected; vault stays locked")
            return False


class ChainedResolver(CredentialResolver):
    def __init__(self, resolvers: list[CredentialResolver]) -> None:
        self._resolvers = resolvers

    def get(self, name: str) -> str | None:
        for resolver in self._resolvers:
            value = resolver.get(name)
            if value is not None:
                return value
        return None


_resolver: CredentialResolver | None = None


def get_resolver() -> CredentialResolver:
    """Return the process-wide default resolver.

    Built lazily so tests can patch ``INITRUNNER_HOME`` before first use.
    Call ``reset_resolver()`` from fixtures that change environment state.
    """
    global _resolver
    if _resolver is None:
        store = LocalEncryptedVault(get_vault_path())
        _resolver = ChainedResolver([EnvVarResolver(), VaultResolver(store)])
    return _resolver


def reset_resolver() -> None:
    global _resolver
    _resolver = None


def require_credential(name: str, *, hint: str | None = None) -> str:
    """Resolve a mandatory credential. Raise ``CredentialNotFound`` when missing.

    Callers that currently raise on a missing env var should switch to this
    helper so the error message is consistent and points users at the
    vault.
    """
    value = get_resolver().get(name)
    if value:
        return value
    message = f"{name} not found. Set it via 'initrunner vault set {name}' or export the env var."
    if hint:
        message = f"{message} {hint}"
    raise CredentialNotFound(message)
