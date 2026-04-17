"""Local encrypted vault using Fernet + scrypt KDF.

File format (``~/.initrunner/vault.enc``):

    {
      "version": 1,
      "kdf": {"algo": "scrypt", "salt": "<b64>", "n": 32768, "r": 8, "p": 1},
      "verifier": "<fernet(b'initrunner-vault-v1')>",
      "created_at": "2026-04-17T...",
      "entries": {"OPENAI_API_KEY": "<fernet-ciphertext>", ...}
    }

The verifier exists so ``unlock`` can detect a wrong passphrase on an empty
vault. Without it, an empty vault plus a wrong passphrase is indistinguishable
from an empty vault plus the correct one until someone calls ``get``.
"""

from __future__ import annotations

import base64
import json
import os
import secrets
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .._compat import require_extra
from .store import VaultLocked, VaultStore, WrongPassphrase

_VERIFIER_PLAINTEXT = b"initrunner-vault-v1"
_SCRYPT_N = 2**15
_SCRYPT_R = 8
_SCRYPT_P = 1
_KEY_LEN = 32
_SALT_LEN = 16
_FILE_MODE = 0o600
_DIR_MODE = 0o700


def _derive_key(passphrase: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    """Derive a Fernet-compatible key from passphrase + scrypt salt."""
    from cryptography.hazmat.primitives.kdf.scrypt import Scrypt  # type: ignore[import-not-found]

    kdf = Scrypt(salt=salt, length=_KEY_LEN, n=n, r=r, p=p)
    raw = kdf.derive(passphrase.encode("utf-8"))
    return base64.urlsafe_b64encode(raw)


class LocalEncryptedVault(VaultStore):
    """A single-file, passphrase-locked vault.

    The vault instance holds the derived Fernet key in memory only while
    unlocked; ``lock()`` clears it. Each entry is encrypted individually
    under the same key so ``rotate()`` can re-encrypt incrementally.
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._fernet: Any = None  # cryptography.fernet.Fernet when unlocked

    @property
    def path(self) -> Path:
        return self._path

    def exists(self) -> bool:
        return self._path.exists()

    def is_unlocked(self) -> bool:
        return self._fernet is not None

    def last_modified(self) -> datetime | None:
        if not self._path.exists():
            return None
        return datetime.fromtimestamp(self._path.stat().st_mtime, tz=UTC)

    def init(self, passphrase: str) -> None:
        """Create a fresh vault. Refuses to overwrite an existing file."""
        require_extra("cryptography")
        if self._path.exists():
            raise FileExistsError(f"vault already exists at {self._path}")
        from cryptography.fernet import Fernet  # type: ignore[import-not-found]

        salt = secrets.token_bytes(_SALT_LEN)
        key = _derive_key(passphrase, salt, _SCRYPT_N, _SCRYPT_R, _SCRYPT_P)
        fernet = Fernet(key)
        verifier = fernet.encrypt(_VERIFIER_PLAINTEXT).decode("ascii")
        payload: dict[str, Any] = {
            "version": 1,
            "kdf": {
                "algo": "scrypt",
                "salt": base64.b64encode(salt).decode("ascii"),
                "n": _SCRYPT_N,
                "r": _SCRYPT_R,
                "p": _SCRYPT_P,
            },
            "verifier": verifier,
            "created_at": datetime.now(UTC).isoformat(),
            "entries": {},
        }
        self._path.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self._path.parent, _DIR_MODE)
        except OSError:
            pass  # not all filesystems support chmod (e.g., some CI mounts)
        self._write_payload(payload)
        self._fernet = fernet

    def unlock(self, passphrase: str) -> None:
        require_extra("cryptography")
        from cryptography.fernet import Fernet, InvalidToken  # type: ignore[import-not-found]

        payload = self._read_payload()
        kdf = payload["kdf"]
        salt = base64.b64decode(kdf["salt"])
        key = _derive_key(passphrase, salt, kdf["n"], kdf["r"], kdf["p"])
        fernet = Fernet(key)
        try:
            if fernet.decrypt(payload["verifier"].encode("ascii")) != _VERIFIER_PLAINTEXT:
                raise WrongPassphrase("invalid passphrase")
        except InvalidToken as exc:
            raise WrongPassphrase("invalid passphrase") from exc
        self._fernet = fernet

    def lock(self) -> None:
        self._fernet = None

    def get(self, name: str) -> str | None:
        from cryptography.fernet import InvalidToken  # type: ignore[import-not-found]

        if self._fernet is None:
            raise VaultLocked("vault is locked")
        payload = self._read_payload()
        entry = payload["entries"].get(name)
        if entry is None:
            return None
        try:
            return self._fernet.decrypt(entry.encode("ascii")).decode("utf-8")
        except InvalidToken as exc:
            raise WrongPassphrase(f"entry {name!r} could not be decrypted") from exc

    def set(self, name: str, value: str) -> None:
        if self._fernet is None:
            raise VaultLocked("vault is locked")
        payload = self._read_payload()
        payload["entries"][name] = self._fernet.encrypt(value.encode("utf-8")).decode("ascii")
        self._write_payload(payload)

    def rm(self, name: str) -> None:
        if self._fernet is None:
            raise VaultLocked("vault is locked")
        payload = self._read_payload()
        if name in payload["entries"]:
            del payload["entries"][name]
            self._write_payload(payload)

    def list_keys(self) -> list[str]:
        payload = self._read_payload()
        return sorted(payload["entries"].keys())

    def export_dict(self) -> dict[str, str]:
        if self._fernet is None:
            raise VaultLocked("vault is locked")
        payload = self._read_payload()
        out: dict[str, str] = {}
        for name, ciphertext in payload["entries"].items():
            out[name] = self._fernet.decrypt(ciphertext.encode("ascii")).decode("utf-8")
        return out

    def import_items(self, items: Iterable[tuple[str, str]]) -> int:
        if self._fernet is None:
            raise VaultLocked("vault is locked")
        payload = self._read_payload()
        count = 0
        for name, value in items:
            payload["entries"][name] = self._fernet.encrypt(value.encode("utf-8")).decode("ascii")
            count += 1
        if count:
            self._write_payload(payload)
        return count

    def rotate(self, new_passphrase: str) -> None:
        from cryptography.fernet import Fernet  # type: ignore[import-not-found]

        if self._fernet is None:
            raise VaultLocked("vault is locked")
        payload = self._read_payload()
        plaintext_entries: dict[str, str] = {}
        for name, ciphertext in payload["entries"].items():
            plaintext_entries[name] = self._fernet.decrypt(ciphertext.encode("ascii")).decode(
                "utf-8"
            )
        new_salt = secrets.token_bytes(_SALT_LEN)
        new_key = _derive_key(new_passphrase, new_salt, _SCRYPT_N, _SCRYPT_R, _SCRYPT_P)
        new_fernet = Fernet(new_key)
        payload["kdf"] = {
            "algo": "scrypt",
            "salt": base64.b64encode(new_salt).decode("ascii"),
            "n": _SCRYPT_N,
            "r": _SCRYPT_R,
            "p": _SCRYPT_P,
        }
        payload["verifier"] = new_fernet.encrypt(_VERIFIER_PLAINTEXT).decode("ascii")
        payload["entries"] = {
            name: new_fernet.encrypt(plaintext.encode("utf-8")).decode("ascii")
            for name, plaintext in plaintext_entries.items()
        }
        self._write_payload(payload)
        self._fernet = new_fernet

    def _read_payload(self) -> dict[str, Any]:
        with self._path.open("rb") as fh:
            return json.loads(fh.read().decode("utf-8"))

    def _write_payload(self, payload: dict[str, Any]) -> None:
        """Atomic write via tempfile + os.replace()."""
        serialized = json.dumps(payload, indent=2, sort_keys=False).encode("utf-8")
        tmp = self._path.with_suffix(self._path.suffix + f".tmp.{os.getpid()}")
        try:
            fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, _FILE_MODE)
            try:
                os.write(fd, serialized)
                os.fsync(fd)
            finally:
                os.close(fd)
            os.replace(tmp, self._path)
        except Exception:
            if tmp.exists():
                tmp.unlink()
            raise
        try:
            os.chmod(self._path, _FILE_MODE)
        except OSError:
            pass
