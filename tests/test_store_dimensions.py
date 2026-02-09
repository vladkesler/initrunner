"""Tests for dimension auto-detection, migration, and validation."""

import sqlite3

import pytest
import sqlite_vec

from initrunner.stores.base import DimensionMismatchError
from initrunner.stores.sqlite_vec import (
    EmbeddingModelChangedError,
    SqliteVecDocumentStore,
    SqliteVecMemoryStore,
    _open_sqlite_vec,
    _read_meta,
    _write_meta,
    wipe_document_store,
)


class TestDocumentStoreDimensions:
    def test_auto_detect_from_existing_db(self, tmp_path):
        """Create store with dimensions=768, reopen without, verify 768 used."""
        db_path = tmp_path / "test.db"
        with SqliteVecDocumentStore(db_path, dimensions=768) as store:
            assert store.dimensions == 768

        with SqliteVecDocumentStore(db_path) as store:
            assert store.dimensions == 768

    def test_dimension_mismatch_raises(self, tmp_path):
        """Create store with 768d, reopen with 1536d, verify error."""
        db_path = tmp_path / "test.db"
        with SqliteVecDocumentStore(db_path, dimensions=768):
            pass

        with pytest.raises(DimensionMismatchError, match=r"768d.*1536d"):
            SqliteVecDocumentStore(db_path, dimensions=1536)

    def test_migration_old_db_defaults_to_1536(self, tmp_path):
        """Old DB without store_meta should default to 1536."""
        db_path = tmp_path / "old.db"
        conn = sqlite3.connect(str(db_path))
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        conn.execute(
            "CREATE TABLE chunks (id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "text TEXT NOT NULL, source TEXT NOT NULL, chunk_index INTEGER NOT NULL)"
        )
        conn.execute("CREATE VIRTUAL TABLE chunks_vec USING vec0(embedding float[1536])")
        conn.commit()
        conn.close()

        with SqliteVecDocumentStore(db_path) as store:
            assert store.dimensions == 1536

    def test_same_dimensions_no_error(self, tmp_path):
        """Reopening with same dimensions should not raise."""
        db_path = tmp_path / "test.db"
        with SqliteVecDocumentStore(db_path, dimensions=768):
            pass

        with SqliteVecDocumentStore(db_path, dimensions=768) as store:
            assert store.dimensions == 768

    def test_new_db_requires_dimensions(self, tmp_path):
        """New DB without dimensions should raise."""
        db_path = tmp_path / "new.db"
        with pytest.raises(DimensionMismatchError, match="no recorded dimensions"):
            SqliteVecDocumentStore(db_path)


class TestMemoryStoreDimensions:
    def test_auto_detect_from_existing_db(self, tmp_path):
        """Create store with dimensions=768, reopen without, verify 768."""
        db_path = tmp_path / "test.db"
        with SqliteVecMemoryStore(db_path, dimensions=768) as store:
            assert store.dimensions == 768

        with SqliteVecMemoryStore(db_path) as store:
            assert store.dimensions == 768

    def test_dimension_mismatch_raises(self, tmp_path):
        """Create store with 768d, reopen with 1536d, verify error."""
        db_path = tmp_path / "test.db"
        with SqliteVecMemoryStore(db_path, dimensions=768):
            pass

        with pytest.raises(DimensionMismatchError, match=r"768d.*1536d"):
            SqliteVecMemoryStore(db_path, dimensions=1536)

    def test_session_operations_without_dimensions(self, tmp_path):
        """Session ops work without knowing dimensions."""
        db_path = tmp_path / "test.db"
        from pydantic_ai.messages import ModelRequest, UserPromptPart

        with SqliteVecMemoryStore(db_path) as store:
            assert store.dimensions is None
            messages = [ModelRequest(parts=[UserPromptPart(content="hello")])]
            store.save_session("s1", "agent-a", messages)
            loaded = store.load_latest_session("agent-a")
            assert loaded is not None
            assert len(loaded) == 1

    def test_lazy_vec_table_creation(self, tmp_path):
        """Vec table created on first add_memory call."""
        db_path = tmp_path / "test.db"
        with SqliteVecMemoryStore(db_path) as store:
            assert store.dimensions is None
            # Add memory triggers vec table creation
            store.add_memory("test fact", "general", [1.0, 0.0, 0.0, 0.0])
            assert store.dimensions == 4
            assert store.count_memories() == 1

    def test_migration_old_db_defaults_to_1536(self, tmp_path):
        """Old DB without store_meta should default to 1536."""
        db_path = tmp_path / "old.db"
        conn = sqlite3.connect(str(db_path))
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        conn.execute(
            "CREATE TABLE memories (id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "content TEXT NOT NULL, category TEXT NOT NULL DEFAULT 'general', "
            "created_at TEXT NOT NULL)"
        )
        conn.execute("CREATE VIRTUAL TABLE memories_vec USING vec0(embedding float[1536])")
        conn.execute(
            "CREATE TABLE sessions (id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "session_id TEXT NOT NULL, agent_name TEXT NOT NULL, "
            "timestamp TEXT NOT NULL, messages_json TEXT NOT NULL)"
        )
        conn.commit()
        conn.close()

        with SqliteVecMemoryStore(db_path) as store:
            assert store.dimensions == 1536


class TestEmbeddingModelTracking:
    """Tests for embedding model identity tracking in store_meta."""

    def test_model_identity_stored_on_first_write(self, tmp_path):
        """Writing model identity to a fresh store should be readable back."""
        db_path = tmp_path / "test.db"
        with SqliteVecDocumentStore(db_path, dimensions=768):
            pass

        conn = _open_sqlite_vec(db_path)
        try:
            assert _read_meta(conn, "embedding_model") is None
            _write_meta(conn, "embedding_model", "openai:text-embedding-3-small")
            assert _read_meta(conn, "embedding_model") == "openai:text-embedding-3-small"
        finally:
            conn.close()

    def test_same_model_no_change(self, tmp_path):
        """Re-writing the same identity should not error."""
        db_path = tmp_path / "test.db"
        with SqliteVecDocumentStore(db_path, dimensions=768):
            pass

        conn = _open_sqlite_vec(db_path)
        try:
            _write_meta(conn, "embedding_model", "openai:text-embedding-3-small")
            _write_meta(conn, "embedding_model", "openai:text-embedding-3-small")
            assert _read_meta(conn, "embedding_model") == "openai:text-embedding-3-small"
        finally:
            conn.close()

    def test_model_identity_updated_on_overwrite(self, tmp_path):
        """Writing a new identity overwrites the old one."""
        db_path = tmp_path / "test.db"
        with SqliteVecDocumentStore(db_path, dimensions=768):
            pass

        conn = _open_sqlite_vec(db_path)
        try:
            _write_meta(conn, "embedding_model", "openai:text-embedding-3-small")
            _write_meta(conn, "embedding_model", "google:text-embedding-004")
            assert _read_meta(conn, "embedding_model") == "google:text-embedding-004"
        finally:
            conn.close()

    def test_legacy_store_returns_none(self, tmp_path):
        """A store without embedding_model key returns None."""
        db_path = tmp_path / "test.db"
        with SqliteVecDocumentStore(db_path, dimensions=768):
            pass

        conn = _open_sqlite_vec(db_path)
        try:
            assert _read_meta(conn, "embedding_model") is None
        finally:
            conn.close()

    def test_wipe_document_store_clears_everything(self, tmp_path):
        """Wiping a store removes chunks, chunks_vec, file_metadata, and store_meta."""
        db_path = tmp_path / "test.db"
        with SqliteVecDocumentStore(db_path, dimensions=4) as store:
            store.add_documents(
                texts=["hello"],
                embeddings=[[1.0, 0.0, 0.0, 0.0]],
                sources=["test.txt"],
                ingested_at="2024-01-01",
            )
            assert store.count() == 1

        conn = _open_sqlite_vec(db_path)
        try:
            _write_meta(conn, "embedding_model", "openai:text-embedding-3-small")
        finally:
            conn.close()

        wipe_document_store(db_path)

        # After wipe, store can be re-created with new dimensions
        with SqliteVecDocumentStore(db_path, dimensions=768) as store:
            assert store.count() == 0
            assert store.dimensions == 768

        conn = _open_sqlite_vec(db_path)
        try:
            assert _read_meta(conn, "embedding_model") is None
            assert _read_meta(conn, "embedding_model") is None
        finally:
            conn.close()

    def test_embedding_model_changed_error(self):
        """EmbeddingModelChangedError can be raised and caught."""
        with pytest.raises(EmbeddingModelChangedError, match="changed"):
            raise EmbeddingModelChangedError("Model changed from A to B")
