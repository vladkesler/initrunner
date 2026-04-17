"""LocalEncryptedVault: round-trip, verifier, atomic writes, rotation."""

from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest

from initrunner.credentials.local_vault import LocalEncryptedVault
from initrunner.credentials.store import VaultLocked, WrongPassphrase


def _make_vault(tmp_path: Path) -> LocalEncryptedVault:
    return LocalEncryptedVault(tmp_path / "vault.enc")


def test_init_creates_file_with_mode_0600(tmp_path: Path) -> None:
    vault = _make_vault(tmp_path)
    vault.init("correct horse battery staple")
    assert vault.exists()
    mode = stat.S_IMODE(vault.path.stat().st_mode)
    assert mode == 0o600


def test_init_refuses_to_overwrite(tmp_path: Path) -> None:
    vault = _make_vault(tmp_path)
    vault.init("pw1")
    with pytest.raises(FileExistsError):
        vault.init("pw2")


def test_roundtrip_set_get(tmp_path: Path) -> None:
    vault = _make_vault(tmp_path)
    vault.init("pw")
    vault.set("OPENAI_API_KEY", "sk-123")
    assert vault.get("OPENAI_API_KEY") == "sk-123"


def test_get_returns_none_for_missing_entry(tmp_path: Path) -> None:
    vault = _make_vault(tmp_path)
    vault.init("pw")
    assert vault.get("NOPE") is None


def test_wrong_passphrase_detected_on_empty_vault(tmp_path: Path) -> None:
    """The whole point of the verifier: empty vault + wrong passphrase must fail."""
    vault = _make_vault(tmp_path)
    vault.init("correct")
    vault.lock()

    reopened = LocalEncryptedVault(vault.path)
    with pytest.raises(WrongPassphrase):
        reopened.unlock("wrong")


def test_correct_passphrase_unlocks_empty_vault(tmp_path: Path) -> None:
    vault = _make_vault(tmp_path)
    vault.init("correct")
    vault.lock()

    reopened = LocalEncryptedVault(vault.path)
    reopened.unlock("correct")
    assert reopened.is_unlocked()


def test_unlock_wrong_passphrase_after_entries(tmp_path: Path) -> None:
    vault = _make_vault(tmp_path)
    vault.init("correct")
    vault.set("K", "v")
    vault.lock()

    reopened = LocalEncryptedVault(vault.path)
    with pytest.raises(WrongPassphrase):
        reopened.unlock("wrong")


def test_locked_vault_refuses_reads_and_writes(tmp_path: Path) -> None:
    vault = _make_vault(tmp_path)
    vault.init("pw")
    vault.set("K", "v")
    vault.lock()

    with pytest.raises(VaultLocked):
        vault.get("K")
    with pytest.raises(VaultLocked):
        vault.set("K2", "v2")
    with pytest.raises(VaultLocked):
        vault.rm("K")
    with pytest.raises(VaultLocked):
        vault.rotate("new")
    with pytest.raises(VaultLocked):
        vault.export_dict()


def test_list_and_rm(tmp_path: Path) -> None:
    vault = _make_vault(tmp_path)
    vault.init("pw")
    vault.set("B", "2")
    vault.set("A", "1")
    assert vault.list_keys() == ["A", "B"]
    vault.rm("A")
    assert vault.list_keys() == ["B"]


def test_export_and_import(tmp_path: Path) -> None:
    vault = _make_vault(tmp_path)
    vault.init("pw")
    vault.set("A", "1")
    vault.set("B", "2")
    assert vault.export_dict() == {"A": "1", "B": "2"}

    other = LocalEncryptedVault(tmp_path / "other.enc")
    other.init("pw2")
    assert other.import_items([("X", "10"), ("Y", "20")]) == 2
    assert other.export_dict() == {"X": "10", "Y": "20"}


def test_rotate_preserves_entries(tmp_path: Path) -> None:
    vault = _make_vault(tmp_path)
    vault.init("old")
    vault.set("A", "1")
    vault.set("B", "2")

    vault.rotate("new")
    vault.lock()

    reopened = LocalEncryptedVault(vault.path)
    with pytest.raises(WrongPassphrase):
        reopened.unlock("old")
    reopened.unlock("new")
    assert reopened.export_dict() == {"A": "1", "B": "2"}


def test_file_contents_are_encrypted(tmp_path: Path) -> None:
    vault = _make_vault(tmp_path)
    vault.init("pw")
    vault.set("OPENAI_API_KEY", "sk-THIS-MUST-NOT-APPEAR-PLAINTEXT")

    raw = vault.path.read_bytes()
    assert b"sk-THIS-MUST-NOT-APPEAR-PLAINTEXT" not in raw

    parsed = json.loads(raw)
    assert "verifier" in parsed
    assert parsed["entries"]["OPENAI_API_KEY"] != "sk-THIS-MUST-NOT-APPEAR-PLAINTEXT"


def test_atomic_write_leaves_no_tmp_on_success(tmp_path: Path) -> None:
    vault = _make_vault(tmp_path)
    vault.init("pw")
    vault.set("K", "v")
    leftover = list(tmp_path.glob("vault.enc.tmp*"))
    assert leftover == []
