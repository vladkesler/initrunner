"""Optional passphrase cache backed by OS keyring.

All functions degrade to no-op / ``None`` when the ``vault-keyring`` extra
isn't installed or no backend is available. Callers never need to handle
import errors themselves.
"""

from __future__ import annotations

import hashlib

from .._compat import is_extra_available
from ..config import get_home_dir

_SERVICE = "initrunner-vault"


def _account() -> str:
    """Stable per-installation identifier so multiple INITRUNNER_HOME dirs can coexist."""
    home = str(get_home_dir())
    return hashlib.sha256(home.encode("utf-8")).hexdigest()[:16]


def _keyring() -> object | None:
    if not is_extra_available("keyring"):
        return None
    try:
        import keyring  # type: ignore[import-not-found]
        from keyring.errors import NoKeyringError  # type: ignore[import-not-found]
    except ImportError:
        return None
    try:
        kr = keyring.get_keyring()
    except NoKeyringError:
        return None
    # Some Linux setups report a "fail" backend (e.g., chainer w/ no backends).
    name = type(kr).__name__.lower()
    if "fail" in name:
        return None
    return keyring


def is_available() -> bool:
    return _keyring() is not None


def load_passphrase() -> str | None:
    kr = _keyring()
    if kr is None:
        return None
    try:
        return kr.get_password(_SERVICE, _account())  # type: ignore[attr-defined]
    except Exception:
        return None


def store_passphrase(passphrase: str) -> bool:
    kr = _keyring()
    if kr is None:
        return False
    try:
        kr.set_password(_SERVICE, _account(), passphrase)  # type: ignore[attr-defined]
        return True
    except Exception:
        return False


def clear_passphrase() -> bool:
    kr = _keyring()
    if kr is None:
        return False
    try:
        kr.delete_password(_SERVICE, _account())  # type: ignore[attr-defined]
        return True
    except Exception:
        return False
