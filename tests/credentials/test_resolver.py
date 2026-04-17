"""ChainedResolver: env wins over vault; locked vault returns None, never prompts."""

from __future__ import annotations

from pathlib import Path

import pytest

from initrunner.credentials import (
    ChainedResolver,
    CredentialNotFound,
    EnvVarResolver,
    VaultResolver,
    get_resolver,
    require_credential,
    reset_resolver,
)
from initrunner.credentials.local_vault import LocalEncryptedVault


def _vault_with(tmp_path: Path, passphrase: str, **entries: str) -> LocalEncryptedVault:
    vault = LocalEncryptedVault(tmp_path / "vault.enc")
    vault.init(passphrase)
    for k, v in entries.items():
        vault.set(k, v)
    return vault


def test_env_wins_over_vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    vault = _vault_with(tmp_path, "pw", OPENAI_API_KEY="vault-value")
    resolver = ChainedResolver([EnvVarResolver(), VaultResolver(vault)])

    monkeypatch.setenv("OPENAI_API_KEY", "env-value")
    assert resolver.get("OPENAI_API_KEY") == "env-value"


def test_vault_fills_when_env_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    vault = _vault_with(tmp_path, "pw", OPENAI_API_KEY="vault-value")
    resolver = ChainedResolver([EnvVarResolver(), VaultResolver(vault)])

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert resolver.get("OPENAI_API_KEY") == "vault-value"


def test_locked_vault_returns_none_never_prompts(
    isolated_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A locked vault must not block on stdin; it must return None quietly."""
    vault = LocalEncryptedVault(isolated_home / "vault.enc")
    vault.init("pw")
    vault.set("K", "v")
    vault.lock()

    # no INITRUNNER_VAULT_PASSPHRASE → can't unlock non-interactively
    monkeypatch.delenv("INITRUNNER_VAULT_PASSPHRASE", raising=False)

    reset_resolver()
    # Patch keyring_cache to return None so the test is deterministic on systems with keyring.
    from initrunner.credentials import keyring_cache

    monkeypatch.setattr(keyring_cache, "load_passphrase", lambda: None)

    assert get_resolver().get("K") is None


def test_vault_unlocks_from_passphrase_env(
    isolated_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = LocalEncryptedVault(isolated_home / "vault.enc")
    vault.init("secret-pw")
    vault.set("K", "v")
    vault.lock()

    monkeypatch.setenv("INITRUNNER_VAULT_PASSPHRASE", "secret-pw")
    reset_resolver()

    assert get_resolver().get("K") == "v"


def test_wrong_passphrase_logged_but_returns_none(
    isolated_home: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    import logging

    # propagate=False is set globally; flip it for this test so caplog sees records.
    monkeypatch.setattr(logging.getLogger("initrunner"), "propagate", True)

    vault = LocalEncryptedVault(isolated_home / "vault.enc")
    vault.init("secret-pw")
    vault.set("K", "v")
    vault.lock()

    monkeypatch.setenv("INITRUNNER_VAULT_PASSPHRASE", "wrong-pw")
    from initrunner.credentials import keyring_cache

    monkeypatch.setattr(keyring_cache, "load_passphrase", lambda: None)
    reset_resolver()

    with caplog.at_level("WARNING"):
        assert get_resolver().get("K") is None
    assert any("passphrase" in rec.message.lower() for rec in caplog.records)


def test_require_credential_raises_actionable_message(
    isolated_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    reset_resolver()

    with pytest.raises(CredentialNotFound) as exc:
        require_credential("OPENAI_API_KEY")
    assert "initrunner vault set OPENAI_API_KEY" in str(exc.value)


def test_require_credential_returns_value_when_found(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FOO_API_KEY", "xyz")
    reset_resolver()
    assert require_credential("FOO_API_KEY") == "xyz"
