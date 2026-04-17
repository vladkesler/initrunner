"""save_env_key: writes to vault when unlockable, else to .env."""

from __future__ import annotations

from pathlib import Path

import pytest

from initrunner.credentials.local_vault import LocalEncryptedVault
from initrunner.services.setup import save_env_key


def test_writes_to_dotenv_when_no_vault(
    isolated_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = save_env_key("FOO_API_KEY", "secret-value")
    assert result is not None
    assert result.name == ".env"
    assert result.exists()
    assert "FOO_API_KEY" in result.read_text()


def test_writes_to_vault_when_unlockable(
    isolated_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = LocalEncryptedVault(isolated_home / "vault.enc")
    vault.init("pw")
    vault.lock()

    monkeypatch.setenv("INITRUNNER_VAULT_PASSPHRASE", "pw")
    from initrunner.credentials import keyring_cache

    monkeypatch.setattr(keyring_cache, "load_passphrase", lambda: None)

    result = save_env_key("FOO_API_KEY", "secret-value")
    assert result is not None
    assert result.name == "vault.enc"

    reopened = LocalEncryptedVault(result)
    reopened.unlock("pw")
    assert reopened.get("FOO_API_KEY") == "secret-value"

    dotenv = isolated_home / ".env"
    assert not dotenv.exists() or "FOO_API_KEY" not in dotenv.read_text()


def test_falls_back_to_dotenv_when_vault_locked_non_interactively(
    isolated_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = LocalEncryptedVault(isolated_home / "vault.enc")
    vault.init("correct")
    vault.lock()

    monkeypatch.delenv("INITRUNNER_VAULT_PASSPHRASE", raising=False)
    from initrunner.credentials import keyring_cache

    monkeypatch.setattr(keyring_cache, "load_passphrase", lambda: None)

    result = save_env_key("FOO_API_KEY", "value")
    assert result is not None
    assert result.name == ".env"
