"""Tests for the vector store."""

import sqlite3

import sqlite_vec

from initrunner.stores.sqlite_vec import SqliteVecDocumentStore as SqliteVecStore


class TestSqliteVecStore:
    def test_create_store(self, tmp_path):
        db_path = tmp_path / "test.db"
        with SqliteVecStore(db_path, dimensions=4):
            assert db_path.exists()

    def test_add_and_count(self, tmp_path):
        db_path = tmp_path / "test.db"
        with SqliteVecStore(db_path, dimensions=4) as store:
            store.add_documents(
                texts=["hello world", "foo bar"],
                embeddings=[[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0]],
                sources=["a.txt", "b.txt"],
            )
            assert store.count() == 2

    def test_query(self, tmp_path):
        db_path = tmp_path / "test.db"
        with SqliteVecStore(db_path, dimensions=4) as store:
            store.add_documents(
                texts=["hello world", "foo bar", "baz qux"],
                embeddings=[
                    [1.0, 0.0, 0.0, 0.0],
                    [0.0, 1.0, 0.0, 0.0],
                    [0.0, 0.0, 1.0, 0.0],
                ],
                sources=["a.txt", "b.txt", "c.txt"],
            )
            results = store.query([1.0, 0.0, 0.0, 0.0], top_k=2)
            assert len(results) == 2
            assert results[0].text == "hello world"

    def test_delete_by_source(self, tmp_path):
        db_path = tmp_path / "test.db"
        with SqliteVecStore(db_path, dimensions=4) as store:
            store.add_documents(
                texts=["hello", "world"],
                embeddings=[[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0]],
                sources=["a.txt", "a.txt"],
            )
            assert store.count() == 2
            deleted = store.delete_by_source("a.txt")
            assert deleted == 2
            assert store.count() == 0

    def test_empty_query(self, tmp_path):
        db_path = tmp_path / "test.db"
        with SqliteVecStore(db_path, dimensions=4) as store:
            results = store.query([1.0, 0.0, 0.0, 0.0], top_k=5)
            assert results == []

    def test_context_manager(self, tmp_path):
        db_path = tmp_path / "test.db"
        with SqliteVecStore(db_path, dimensions=4) as store:
            store.add_documents(
                texts=["test"],
                embeddings=[[1.0, 0.0, 0.0, 0.0]],
                sources=["t.txt"],
            )
        # After close, file should still exist
        assert db_path.exists()

    def test_query_with_exact_source_filter(self, tmp_path):
        db_path = tmp_path / "test.db"
        with SqliteVecStore(db_path, dimensions=4) as store:
            store.add_documents(
                texts=["hello world", "foo bar", "baz qux"],
                embeddings=[
                    [1.0, 0.0, 0.0, 0.0],
                    [0.9, 0.1, 0.0, 0.0],
                    [0.0, 0.0, 1.0, 0.0],
                ],
                sources=["a.txt", "b.txt", "a.txt"],
            )
            # Filter to only a.txt — should return both a.txt chunks
            results = store.query([1.0, 0.0, 0.0, 0.0], top_k=5, source_filter="a.txt")
            assert all(r.source == "a.txt" for r in results)
            assert len(results) == 2

    def test_query_with_glob_filter(self, tmp_path):
        db_path = tmp_path / "test.db"
        with SqliteVecStore(db_path, dimensions=4) as store:
            store.add_documents(
                texts=["hello", "foo", "bar"],
                embeddings=[
                    [1.0, 0.0, 0.0, 0.0],
                    [0.9, 0.1, 0.0, 0.0],
                    [0.0, 1.0, 0.0, 0.0],
                ],
                sources=["doc.md", "doc.txt", "notes.md"],
            )
            results = store.query([1.0, 0.0, 0.0, 0.0], top_k=5, source_filter="*.md")
            assert all(r.source.endswith(".md") for r in results)
            assert len(results) == 2

    def test_query_filter_no_matches(self, tmp_path):
        db_path = tmp_path / "test.db"
        with SqliteVecStore(db_path, dimensions=4) as store:
            store.add_documents(
                texts=["hello"],
                embeddings=[[1.0, 0.0, 0.0, 0.0]],
                sources=["a.txt"],
            )
            results = store.query([1.0, 0.0, 0.0, 0.0], top_k=5, source_filter="b.txt")
            assert results == []

    def test_add_documents_with_ingested_at(self, tmp_path):
        db_path = tmp_path / "test.db"
        with SqliteVecStore(db_path, dimensions=4) as store:
            store.add_documents(
                texts=["hello"],
                embeddings=[[1.0, 0.0, 0.0, 0.0]],
                sources=["a.txt"],
                ingested_at="2025-01-01T00:00:00",
            )
            row = store._conn.execute(  # type: ignore[attr-defined]
                "SELECT ingested_at FROM chunks WHERE source = ?", ("a.txt",)
            ).fetchone()
            assert row[0] == "2025-01-01T00:00:00"

    def test_file_metadata_upsert_and_get(self, tmp_path):
        db_path = tmp_path / "test.db"
        with SqliteVecStore(db_path, dimensions=4) as store:
            store.upsert_file_metadata("a.txt", "abc123", 1000.0, "2025-01-01T00:00:00", 5)
            meta = store.get_file_metadata("a.txt")
            assert meta is not None
            assert meta[0] == "abc123"
            assert meta[1] == 1000.0
            assert meta[2] == "2025-01-01T00:00:00"

    def test_file_metadata_overwrite(self, tmp_path):
        db_path = tmp_path / "test.db"
        with SqliteVecStore(db_path, dimensions=4) as store:
            store.upsert_file_metadata("a.txt", "hash1", 1000.0, "2025-01-01", 5)
            store.upsert_file_metadata("a.txt", "hash2", 2000.0, "2025-02-01", 10)
            meta = store.get_file_metadata("a.txt")
            assert meta is not None
            assert meta[0] == "hash2"
            assert meta[1] == 2000.0
            assert meta[2] == "2025-02-01"

    def test_file_metadata_get_nonexistent(self, tmp_path):
        db_path = tmp_path / "test.db"
        with SqliteVecStore(db_path, dimensions=4) as store:
            assert store.get_file_metadata("nonexistent.txt") is None

    def test_file_metadata_delete(self, tmp_path):
        db_path = tmp_path / "test.db"
        with SqliteVecStore(db_path, dimensions=4) as store:
            store.upsert_file_metadata("a.txt", "hash1", 1000.0, "2025-01-01", 5)
            store.delete_file_metadata("a.txt")
            assert store.get_file_metadata("a.txt") is None

    def test_list_sources(self, tmp_path):
        db_path = tmp_path / "test.db"
        with SqliteVecStore(db_path, dimensions=4) as store:
            store.upsert_file_metadata("a.txt", "h1", 1.0, "t1", 1)
            store.upsert_file_metadata("b.txt", "h2", 2.0, "t2", 2)
            sources = store.list_sources()
            assert sorted(sources) == ["a.txt", "b.txt"]

    def test_replace_source(self, tmp_path):
        db_path = tmp_path / "test.db"
        with SqliteVecStore(db_path, dimensions=4) as store:
            # Add initial data
            store.add_documents(
                texts=["old chunk"],
                embeddings=[[1.0, 0.0, 0.0, 0.0]],
                sources=["a.txt"],
            )
            assert store.count() == 1

            # Replace with new data
            count = store.replace_source(
                source="a.txt",
                texts=["new chunk 1", "new chunk 2"],
                embeddings=[[0.0, 1.0, 0.0, 0.0], [0.0, 0.0, 1.0, 0.0]],
                ingested_at="2025-01-01",
                content_hash="newhash",
                last_modified=2000.0,
            )
            assert count == 2
            assert store.count() == 2
            meta = store.get_file_metadata("a.txt")
            assert meta is not None
            assert meta[0] == "newhash"

    def test_migration_adds_ingested_at(self, tmp_path):
        """Open an old-schema DB (without ingested_at), verify migration adds it."""
        db_path = tmp_path / "old.db"
        # Create an old-schema DB manually (without ingested_at column)
        conn = sqlite3.connect(str(db_path))
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        conn.execute(
            "CREATE TABLE chunks (id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "text TEXT NOT NULL, source TEXT NOT NULL, chunk_index INTEGER NOT NULL)"
        )
        conn.execute("CREATE INDEX idx_chunks_source ON chunks (source)")
        conn.execute("CREATE VIRTUAL TABLE chunks_vec USING vec0(embedding float[4])")
        conn.execute(
            "INSERT INTO chunks (text, source, chunk_index) VALUES (?, ?, ?)",
            ("hello", "a.txt", 0),
        )
        conn.execute(
            "INSERT INTO chunks_vec (rowid, embedding) VALUES (?, ?)",
            (1, sqlite_vec.serialize_float32([1.0, 0.0, 0.0, 0.0])),
        )
        conn.commit()
        conn.close()

        # Now open with SqliteVecStore — migration should add ingested_at.
        # Old DBs without store_meta default to 1536, so pass no dimensions
        # (auto-detected) to avoid mismatch with the actual 4d vec table.
        with SqliteVecStore(db_path) as store:
            columns = {
                row[1]
                for row in store._conn.execute("PRAGMA table_info(chunks)").fetchall()  # type: ignore[attr-defined]
            }
            assert "ingested_at" in columns
            # Old data should still be accessible
            assert store.count() == 1
