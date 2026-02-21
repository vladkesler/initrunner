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


def test_zvec_store_creates_private_dir(tmp_path):
    from initrunner.stores.zvec_store import ZvecDocumentStore

    store_path = tmp_path / "sub" / "store.zvec"
    with ZvecDocumentStore(store_path, dimensions=4):
        assert stat.S_IMODE(store_path.stat().st_mode) == 0o700
