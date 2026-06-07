"""Consent precedence: DO_NOT_TRACK, INITRUNNER_TELEMETRY, CI, persisted consent."""

from __future__ import annotations

import pytest

from initrunner.config import get_home_dir, get_telemetry_config_path


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("INITRUNNER_HOME", str(tmp_path))
    for var in ("DO_NOT_TRACK", "INITRUNNER_TELEMETRY", "CI"):
        monkeypatch.delenv(var, raising=False)
    get_home_dir.cache_clear()
    return tmp_path


def test_do_not_track_beats_explicit_opt_in(home, monkeypatch):
    from initrunner.telemetry import _config

    monkeypatch.setenv("DO_NOT_TRACK", "1")
    monkeypatch.setenv("INITRUNNER_TELEMETRY", "on")
    enabled, reason = _config.resolve_enabled()
    assert enabled is False
    assert reason == "do-not-track"


@pytest.mark.parametrize("value", ["0", "false", ""])
def test_do_not_track_falsey_does_not_disable(home, monkeypatch, value):
    from initrunner.telemetry import _config

    # With consent granted, a falsey DO_NOT_TRACK must not force telemetry off.
    _config.set_consent(True)
    monkeypatch.setenv("DO_NOT_TRACK", value)
    enabled, _ = _config.resolve_enabled()
    assert enabled is True


@pytest.mark.parametrize("value", ["off", "0", "false", "disable", "no"])
def test_env_opt_out_values(home, monkeypatch, value):
    from initrunner.telemetry import _config

    monkeypatch.setenv("INITRUNNER_TELEMETRY", value)
    enabled, reason = _config.resolve_enabled()
    assert enabled is False
    assert reason == "env-opt-out"


@pytest.mark.parametrize("value", ["on", "1", "true"])
def test_env_opt_in_beats_ci(home, monkeypatch, value):
    from initrunner.telemetry import _config

    monkeypatch.setenv("CI", "true")
    monkeypatch.setenv("INITRUNNER_TELEMETRY", value)
    enabled, reason = _config.resolve_enabled()
    assert enabled is True
    assert reason == "env-opt-in"


def test_ci_default_off(home, monkeypatch):
    from initrunner.telemetry import _config

    monkeypatch.setenv("CI", "true")
    enabled, reason = _config.resolve_enabled()
    assert enabled is False
    assert reason == "ci"


def test_persisted_consent_denied(home):
    from initrunner.telemetry import _config

    _config.set_consent(False)
    enabled, reason = _config.resolve_enabled()
    assert enabled is False
    assert reason == "consent-denied"


def test_persisted_consent_granted(home):
    from initrunner.telemetry import _config

    _config.set_consent(True)
    enabled, reason = _config.resolve_enabled()
    assert enabled is True
    assert reason == "consent-granted"


def test_default_unset_is_off(home):
    from initrunner.telemetry import _config

    # Opt-in: an undecided install sends nothing until the user is asked.
    enabled, reason = _config.resolve_enabled()
    assert enabled is False
    assert reason == "unset"


def test_resolve_does_not_create_file_when_disabled(home, monkeypatch):
    from initrunner.telemetry import _config

    monkeypatch.setenv("DO_NOT_TRACK", "1")
    _config.resolve_enabled()
    assert not get_telemetry_config_path().exists()


def test_resolve_does_not_create_file_when_unset(home):
    from initrunner.telemetry import _config

    # The opt-in default path must also stay read-only.
    _config.resolve_enabled()
    assert not get_telemetry_config_path().exists()
