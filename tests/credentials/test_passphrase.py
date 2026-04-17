"""Passphrase acquisition policy: never block on stdin in non-interactive contexts."""

from __future__ import annotations

import pytest

from initrunner.credentials import keyring_cache, passphrase


def test_from_env_returns_none_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("INITRUNNER_VAULT_PASSPHRASE", raising=False)
    assert passphrase.from_env() is None


def test_from_env_returns_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INITRUNNER_VAULT_PASSPHRASE", "abc")
    assert passphrase.from_env() == "abc"


def test_from_env_treats_empty_as_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INITRUNNER_VAULT_PASSPHRASE", "")
    assert passphrase.from_env() is None


def test_acquire_non_interactive_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("INITRUNNER_VAULT_PASSPHRASE", raising=False)
    monkeypatch.setattr(keyring_cache, "load_passphrase", lambda: None)
    assert passphrase.acquire(interactive=False) is None


def test_acquire_prefers_env_over_keyring(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INITRUNNER_VAULT_PASSPHRASE", "from-env")
    monkeypatch.setattr(keyring_cache, "load_passphrase", lambda: "from-keyring")
    assert passphrase.acquire(interactive=False) == "from-env"


def test_acquire_falls_back_to_keyring(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("INITRUNNER_VAULT_PASSPHRASE", raising=False)
    monkeypatch.setattr(keyring_cache, "load_passphrase", lambda: "from-keyring")
    assert passphrase.acquire(interactive=False) == "from-keyring"


def test_acquire_interactive_skipped_when_stdin_not_tty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Even with interactive=True, a non-TTY stdin must not prompt."""
    import sys

    monkeypatch.delenv("INITRUNNER_VAULT_PASSPHRASE", raising=False)
    monkeypatch.setattr(keyring_cache, "load_passphrase", lambda: None)

    class FakeStdin:
        def isatty(self) -> bool:
            return False

    monkeypatch.setattr(sys, "stdin", FakeStdin())

    assert passphrase.acquire(interactive=True) is None


def test_prompt_interactive_confirm_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    import getpass as _getpass

    responses = iter(["first", "second"])
    monkeypatch.setattr(_getpass, "getpass", lambda prompt="": next(responses))

    with pytest.raises(ValueError, match="passphrases did not match"):
        passphrase.prompt_interactive(confirm=True)
