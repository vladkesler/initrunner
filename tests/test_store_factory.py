"""Tests for store factory functions."""

from initrunner.stores.base import StoreBackend
from initrunner.stores.factory import create_document_store, create_memory_store
from initrunner.stores.zvec_store import ZvecDocumentStore, ZvecMemoryStore


class TestCreateDocumentStore:
    def test_returns_zvec(self, tmp_path):
        store_path = tmp_path / "test.zvec"
        store = create_document_store(StoreBackend.ZVEC, store_path, dimensions=4)
        assert isinstance(store, ZvecDocumentStore)
        store.close()

    def test_passes_dimensions(self, tmp_path):
        store_path = tmp_path / "test.zvec"
        store = create_document_store(StoreBackend.ZVEC, store_path, dimensions=768)
        assert store.dimensions == 768
        store.close()


class TestCreateMemoryStore:
    def test_returns_zvec(self, tmp_path):
        store_path = tmp_path / "test.zvec"
        store = create_memory_store(StoreBackend.ZVEC, store_path, dimensions=4)
        assert isinstance(store, ZvecMemoryStore)
        store.close()

    def test_passes_dimensions(self, tmp_path):
        store_path = tmp_path / "test.zvec"
        store = create_memory_store(StoreBackend.ZVEC, store_path, dimensions=768)
        assert store.dimensions == 768
        store.close()

    def test_no_dimensions_ok(self, tmp_path):
        """Memory store can be created without dimensions for session-only use."""
        store_path = tmp_path / "test.zvec"
        store = create_memory_store(StoreBackend.ZVEC, store_path)
        assert store.dimensions is None
        store.close()
