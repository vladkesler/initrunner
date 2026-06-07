"""Telemetry consent state: install id, persistence, file mode, concurrency."""

from __future__ import annotations

import stat
import threading
import uuid

import pytest

from initrunner.config import get_home_dir, get_telemetry_config_path


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("INITRUNNER_HOME", str(tmp_path))
    for var in ("DO_NOT_TRACK", "INITRUNNER_TELEMETRY", "CI"):
        monkeypatch.delenv(var, raising=False)
    get_home_dir.cache_clear()
    return tmp_path


def test_install_id_is_uuid4_and_stable(home):
    from initrunner.telemetry import _config

    first = _config.load_or_create()
    assert uuid.UUID(first.install_id).version == 4
    assert _config.load_or_create().install_id == first.install_id


def test_file_created_mode_0600(home):
    from initrunner.telemetry import _config

    _config.load_or_create()
    mode = stat.S_IMODE(get_telemetry_config_path().stat().st_mode)
    assert mode == 0o600


def test_defaults_on_corrupt_file(home):
    from initrunner.telemetry import _config

    path = get_telemetry_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("not json {{{")
    assert _config._load_raw() is None
    # load_or_create recovers and rewrites a valid record
    state = _config.load_or_create()
    assert state.install_id
    assert _config._load_raw() is not None


def test_disable_enable_preserves_id_and_mode(home):
    from initrunner.telemetry import _config

    original = _config.load_or_create().install_id

    _config.set_enabled(False)
    disabled = _config._load_raw()
    assert disabled is not None and disabled.enabled is False
    assert stat.S_IMODE(get_telemetry_config_path().stat().st_mode) == 0o600

    _config.set_enabled(True)
    reloaded = _config._load_raw()
    assert reloaded is not None
    assert reloaded.enabled is True
    assert reloaded.install_id == original


def test_reset_rotates_id(home):
    from initrunner.telemetry import _config

    old = _config.load_or_create().install_id
    new = _config.reset_install_id().install_id
    assert new != old
    reloaded = _config._load_raw()
    assert reloaded is not None and reloaded.install_id == new


def test_concurrent_first_create_agree_on_one_id(home):
    from initrunner.telemetry import _config

    results: list[str] = []
    barrier = threading.Barrier(8)

    def worker() -> None:
        barrier.wait()
        results.append(_config.load_or_create().install_id)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(results) == 8
    assert len(set(results)) == 1


def test_install_id_differs_from_keyring_account(home):
    from initrunner.credentials import keyring_cache
    from initrunner.telemetry import _config

    install_id = _config.load_or_create().install_id
    # The keyring account hash is SHA256(home)[:16], a weak fingerprint; the
    # telemetry id must be a fresh random UUID, never that hash.
    assert install_id != keyring_cache._account()
