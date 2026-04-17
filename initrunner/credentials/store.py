"""Abstract vault store + shared exceptions."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable


class VaultLocked(RuntimeError):
    """Raised when a vault operation requires an unlocked vault but isn't."""


class WrongPassphrase(RuntimeError):
    """Raised when the supplied passphrase fails the verifier check."""


class VaultStore(ABC):
    """Read+write interface for a credential vault.

    Implementations encrypt at rest. ``get`` returns ``None`` for missing
    entries; ``require_credential`` on the resolver side turns that into a
    loud, actionable error.
    """

    @abstractmethod
    def exists(self) -> bool: ...

    @abstractmethod
    def is_unlocked(self) -> bool: ...

    @abstractmethod
    def unlock(self, passphrase: str) -> None: ...

    @abstractmethod
    def lock(self) -> None: ...

    @abstractmethod
    def get(self, name: str) -> str | None: ...

    @abstractmethod
    def set(self, name: str, value: str) -> None: ...

    @abstractmethod
    def rm(self, name: str) -> None: ...

    @abstractmethod
    def list_keys(self) -> list[str]: ...

    @abstractmethod
    def export_dict(self) -> dict[str, str]: ...

    @abstractmethod
    def import_items(self, items: Iterable[tuple[str, str]]) -> int: ...

    @abstractmethod
    def rotate(self, new_passphrase: str) -> None: ...
