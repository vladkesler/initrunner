"""Tests for store factory functions."""

import pytest

from initrunner.stores.base import StoreBackend
from initrunner.stores.factory import create_document_store, create_memory_store
from initrunner.stores.sqlite_vec import SqliteVecDocumentStore, SqliteVecMemoryStore


class TestCreateDocumentStore:
    def test_returns_sqlite_vec(self, tmp_path):
        db_path = tmp_path / "test.db"
        store = create_document_store(StoreBackend.SQLITE_VEC, db_path, dimensions=4)
        assert isinstance(store, SqliteVecDocumentStore)
        store.close()

    def test_unknown_backend_raises(self, tmp_path):
        db_path = tmp_path / "test.db"
        with pytest.raises(ValueError, match="Unknown document store backend"):
            create_document_store("unknown", db_path, dimensions=4)  # type: ignore[arg-type]

    def test_passes_dimensions(self, tmp_path):
        db_path = tmp_path / "test.db"
        store = create_document_store(StoreBackend.SQLITE_VEC, db_path, dimensions=768)
        assert store.dimensions == 768
        store.close()


class TestCreateMemoryStore:
    def test_returns_sqlite_vec(self, tmp_path):
        db_path = tmp_path / "test.db"
        store = create_memory_store(StoreBackend.SQLITE_VEC, db_path, dimensions=4)
        assert isinstance(store, SqliteVecMemoryStore)
        store.close()

    def test_unknown_backend_raises(self, tmp_path):
        db_path = tmp_path / "test.db"
        with pytest.raises(ValueError, match="Unknown memory store backend"):
            create_memory_store("unknown", db_path, dimensions=4)  # type: ignore[arg-type]

    def test_passes_dimensions(self, tmp_path):
        db_path = tmp_path / "test.db"
        store = create_memory_store(StoreBackend.SQLITE_VEC, db_path, dimensions=768)
        assert store.dimensions == 768
        store.close()

    def test_no_dimensions_ok(self, tmp_path):
        """Memory store can be created without dimensions for session-only use."""
        db_path = tmp_path / "test.db"
        store = create_memory_store(StoreBackend.SQLITE_VEC, db_path)
        assert store.dimensions is None
        store.close()
