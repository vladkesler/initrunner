"""Tests for initrunner._paths secure-path helpers."""

import stat
import sys

import pytest

from initrunner._paths import ensure_private_dir, secure_database

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="Unix permissions only")


def test_ensure_private_dir_creates_with_0o700(tmp_path):
    target = tmp_path / "newdir"
    ensure_private_dir(target)
    assert target.is_dir()
    assert stat.S_IMODE(target.stat().st_mode) == 0o700


def test_ensure_private_dir_tightens_existing(tmp_path):
    target = tmp_path / "lax"
    target.mkdir(mode=0o755)
    assert stat.S_IMODE(target.stat().st_mode) == 0o755
    ensure_private_dir(target)
    assert stat.S_IMODE(target.stat().st_mode) == 0o700


def test_ensure_private_dir_skips_unowned_existing(tmp_path, monkeypatch):
    """A pre-existing directory we do not own is left untouched, never chmod'd."""
    import initrunner._paths as paths

    target = tmp_path / "shared"
    target.mkdir(mode=0o755)
    monkeypatch.setattr(paths, "_owned_by_current_user", lambda p: False)
    ensure_private_dir(target)  # must not raise
    # permissions stay as the real owner set them, not forced to 0o700
    assert stat.S_IMODE(target.stat().st_mode) == 0o755


def test_ensure_private_dir_survives_chmod_permission_error(tmp_path, monkeypatch):
    """A directory we cannot chmod (the /tmp case) must not crash the caller."""
    target = tmp_path / "locked"
    target.mkdir(mode=0o755)

    def _boom(*_args, **_kwargs):
        raise PermissionError(1, "Operation not permitted")

    monkeypatch.setattr("pathlib.Path.chmod", _boom)
    ensure_private_dir(target)  # PermissionError is swallowed, no raise


def test_audit_logger_in_unowned_parent_does_not_crash(tmp_path, monkeypatch):
    """Regression: --audit-db under a parent we do not own (e.g. /tmp) must not crash init."""
    import initrunner._paths as paths
    from initrunner.audit.logger import AuditLogger

    parent = tmp_path / "shared_tmp"
    parent.mkdir(mode=0o755)
    # Simulate a shared, not-owned parent like /tmp.
    monkeypatch.setattr(paths, "_owned_by_current_user", lambda p: False)
    logger = AuditLogger(db_path=parent / "audit.db")
    try:
        db = parent / "audit.db"
        assert db.exists()
        # the parent's permissions are left alone ...
        assert stat.S_IMODE(parent.stat().st_mode) == 0o755
        # ... while the data file itself is still locked down to owner-only.
        assert stat.S_IMODE(db.stat().st_mode) == 0o600
    finally:
        logger.close()


def test_secure_database_sets_0o600(tmp_path):
    db = tmp_path / "test.db"
    db.write_text("data")
    db.chmod(0o644)
    secure_database(db)
    assert stat.S_IMODE(db.stat().st_mode) == 0o600


def test_secure_database_noop_missing_file(tmp_path):
    missing = tmp_path / "nonexistent.db"
    secure_database(missing)  # should not raise


def test_audit_logger_creates_private_dir(tmp_path):
    from initrunner.audit.logger import AuditLogger

    db_path = tmp_path / "sub" / "audit.db"
    logger = AuditLogger(db_path=db_path)
    try:
        assert stat.S_IMODE(db_path.parent.stat().st_mode) == 0o700
        assert stat.S_IMODE(db_path.stat().st_mode) == 0o600
    finally:
        logger.close()


def test_lance_store_creates_private_dir(tmp_path):
    from initrunner.stores.lance_store import LanceDocumentStore

    store_path = tmp_path / "sub" / "store.lance"
    with LanceDocumentStore(store_path, dimensions=4):
        assert stat.S_IMODE(store_path.stat().st_mode) == 0o700
