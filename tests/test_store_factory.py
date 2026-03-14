"""Tests for store factory functions."""

from initrunner.stores.base import StoreBackend
from initrunner.stores.factory import create_document_store, create_memory_store
from initrunner.stores.lance_store import LanceDocumentStore, LanceMemoryStore


class TestCreateDocumentStore:
    def test_returns_lancedb(self, tmp_path):
        store_path = tmp_path / "test.lance"
        store = create_document_store(StoreBackend.LANCEDB, store_path, dimensions=4)
        assert isinstance(store, LanceDocumentStore)
        store.close()

    def test_passes_dimensions(self, tmp_path):
        store_path = tmp_path / "test.lance"
        store = create_document_store(StoreBackend.LANCEDB, store_path, dimensions=768)
        assert store.dimensions == 768
        store.close()


class TestCreateMemoryStore:
    def test_returns_lancedb(self, tmp_path):
        store_path = tmp_path / "test.lance"
        store = create_memory_store(StoreBackend.LANCEDB, store_path, dimensions=4)
        assert isinstance(store, LanceMemoryStore)
        store.close()

    def test_passes_dimensions(self, tmp_path):
        store_path = tmp_path / "test.lance"
        store = create_memory_store(StoreBackend.LANCEDB, store_path, dimensions=768)
        assert store.dimensions == 768
        store.close()

    def test_no_dimensions_ok(self, tmp_path):
        """Memory store can be created without dimensions for session-only use."""
        store_path = tmp_path / "test.lance"
        store = create_memory_store(StoreBackend.LANCEDB, store_path)
        assert store.dimensions is None
        store.close()
