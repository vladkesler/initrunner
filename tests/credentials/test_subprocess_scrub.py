"""Regression: INITRUNNER_VAULT_PASSPHRASE + *_PASSPHRASE are scrubbed from child env."""

from __future__ import annotations

import pytest

from initrunner.agent._subprocess import DEFAULT_SENSITIVE_ENV_SUFFIXES, scrub_env


def test_passphrase_suffix_in_defaults() -> None:
    assert "_PASSPHRASE" in DEFAULT_SENSITIVE_ENV_SUFFIXES


def test_scrub_removes_passphrase_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INITRUNNER_VAULT_PASSPHRASE", "hunter2")
    monkeypatch.setenv("MY_APP_PASSPHRASE", "another")
    monkeypatch.setenv("HARMLESS_VAR", "stay")
    monkeypatch.setenv("PATH_OK", "/usr/bin")

    scrubbed = scrub_env()

    assert "INITRUNNER_VAULT_PASSPHRASE" not in scrubbed
    assert "MY_APP_PASSPHRASE" not in scrubbed
    assert scrubbed.get("HARMLESS_VAR") == "stay"
    assert scrubbed.get("PATH_OK") == "/usr/bin"
