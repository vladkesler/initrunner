"""Tests for dimension auto-detection, migration, and validation."""

import pytest

from initrunner.stores.base import DimensionMismatchError, EmbeddingModelChangedError
from initrunner.stores.zvec_store import (
    ZvecDocumentStore,
    ZvecMemoryStore,
    wipe_document_store,
)


class TestDocumentStoreDimensions:
    def test_auto_detect_from_existing_db(self, tmp_path):
        """Create store with dimensions=768, reopen without, verify 768 used."""
        store_path = tmp_path / "test.zvec"
        with ZvecDocumentStore(store_path, dimensions=768) as store:
            assert store.dimensions == 768

        with ZvecDocumentStore(store_path) as store:
            assert store.dimensions == 768

    def test_dimension_mismatch_raises(self, tmp_path):
        """Create store with 768d, reopen with 1536d, verify error."""
        store_path = tmp_path / "test.zvec"
        with ZvecDocumentStore(store_path, dimensions=768):
            pass

        with pytest.raises(DimensionMismatchError, match=r"768d.*1536d"):
            ZvecDocumentStore(store_path, dimensions=1536)

    def test_same_dimensions_no_error(self, tmp_path):
        """Reopening with same dimensions should not raise."""
        store_path = tmp_path / "test.zvec"
        with ZvecDocumentStore(store_path, dimensions=768):
            pass

        with ZvecDocumentStore(store_path, dimensions=768) as store:
            assert store.dimensions == 768

    def test_new_db_requires_dimensions(self, tmp_path):
        """New DB without dimensions should raise."""
        store_path = tmp_path / "new.zvec"
        with pytest.raises(DimensionMismatchError, match="no recorded dimensions"):
            ZvecDocumentStore(store_path)


class TestMemoryStoreDimensions:
    def test_auto_detect_from_existing_db(self, tmp_path):
        """Create store with dimensions=768, reopen without, verify 768."""
        store_path = tmp_path / "test.zvec"
        with ZvecMemoryStore(store_path, dimensions=768) as store:
            assert store.dimensions == 768

        with ZvecMemoryStore(store_path) as store:
            assert store.dimensions == 768

    def test_dimension_mismatch_raises(self, tmp_path):
        """Create store with 768d, reopen with 1536d, verify error."""
        store_path = tmp_path / "test.zvec"
        with ZvecMemoryStore(store_path, dimensions=768):
            pass

        with pytest.raises(DimensionMismatchError, match=r"768d.*1536d"):
            ZvecMemoryStore(store_path, dimensions=1536)

    def test_session_operations_without_dimensions(self, tmp_path):
        """Session ops work without knowing dimensions."""
        store_path = tmp_path / "test.zvec"
        from pydantic_ai.messages import ModelRequest, UserPromptPart

        with ZvecMemoryStore(store_path) as store:
            assert store.dimensions is None
            messages = [ModelRequest(parts=[UserPromptPart(content="hello")])]
            store.save_session("s1", "agent-a", messages)
            loaded = store.load_latest_session("agent-a")
            assert loaded is not None
            assert len(loaded) == 1

    def test_lazy_vec_table_creation(self, tmp_path):
        """Vec collection created on first add_memory call."""
        store_path = tmp_path / "test.zvec"
        with ZvecMemoryStore(store_path) as store:
            assert store.dimensions is None
            # Add memory triggers vec collection creation
            store.add_memory("test fact", "general", [1.0, 0.0, 0.0, 0.0])
            assert store.dimensions == 4
            assert store.count_memories() == 1


class TestEmbeddingModelTracking:
    """Tests for embedding model identity tracking in store_meta."""

    def test_model_identity_stored_on_first_write(self, tmp_path):
        """Writing model identity to a fresh store should be readable back."""
        store_path = tmp_path / "test.zvec"
        with ZvecDocumentStore(store_path, dimensions=768) as store:
            assert store.read_store_meta("embedding_model") is None
            store.write_store_meta("embedding_model", "openai:text-embedding-3-small")
            assert store.read_store_meta("embedding_model") == "openai:text-embedding-3-small"

    def test_same_model_no_change(self, tmp_path):
        """Re-writing the same identity should not error."""
        store_path = tmp_path / "test.zvec"
        with ZvecDocumentStore(store_path, dimensions=768) as store:
            store.write_store_meta("embedding_model", "openai:text-embedding-3-small")
            store.write_store_meta("embedding_model", "openai:text-embedding-3-small")
            assert store.read_store_meta("embedding_model") == "openai:text-embedding-3-small"

    def test_model_identity_updated_on_overwrite(self, tmp_path):
        """Writing a new identity overwrites the old one."""
        store_path = tmp_path / "test.zvec"
        with ZvecDocumentStore(store_path, dimensions=768) as store:
            store.write_store_meta("embedding_model", "openai:text-embedding-3-small")
            store.write_store_meta("embedding_model", "google:text-embedding-004")
            assert store.read_store_meta("embedding_model") == "google:text-embedding-004"

    def test_legacy_store_returns_none(self, tmp_path):
        """A store without embedding_model key returns None."""
        store_path = tmp_path / "test.zvec"
        with ZvecDocumentStore(store_path, dimensions=768) as store:
            assert store.read_store_meta("embedding_model") is None

    def test_wipe_document_store_clears_everything(self, tmp_path):
        """Wiping a store removes all data."""
        store_path = tmp_path / "test.zvec"
        with ZvecDocumentStore(store_path, dimensions=4) as store:
            store.add_documents(
                texts=["hello"],
                embeddings=[[1.0, 0.0, 0.0, 0.0]],
                sources=["test.txt"],
                ingested_at="2024-01-01",
            )
            assert store.count() == 1
            store.write_store_meta("embedding_model", "openai:text-embedding-3-small")

        wipe_document_store(store_path)

        # After wipe, store can be re-created with new dimensions
        with ZvecDocumentStore(store_path, dimensions=768) as store:
            assert store.count() == 0
            assert store.dimensions == 768
            assert store.read_store_meta("embedding_model") is None

    def test_embedding_model_changed_error(self):
        """EmbeddingModelChangedError can be raised and caught."""
        with pytest.raises(EmbeddingModelChangedError, match="changed"):
            raise EmbeddingModelChangedError("Model changed from A to B")
