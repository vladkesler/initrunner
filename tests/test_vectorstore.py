"""Tests for the vector store."""

from initrunner.stores.zvec_store import ZvecDocumentStore


class TestZvecDocumentStore:
    def test_create_store(self, tmp_path):
        store_path = tmp_path / "test.zvec"
        with ZvecDocumentStore(store_path, dimensions=4):
            assert store_path.exists()

    def test_add_and_count(self, tmp_path):
        store_path = tmp_path / "test.zvec"
        with ZvecDocumentStore(store_path, dimensions=4) as store:
            store.add_documents(
                texts=["hello world", "foo bar"],
                embeddings=[[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0]],
                sources=["a.txt", "b.txt"],
            )
            assert store.count() == 2

    def test_query(self, tmp_path):
        store_path = tmp_path / "test.zvec"
        with ZvecDocumentStore(store_path, dimensions=4) as store:
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
        store_path = tmp_path / "test.zvec"
        with ZvecDocumentStore(store_path, dimensions=4) as store:
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
        store_path = tmp_path / "test.zvec"
        with ZvecDocumentStore(store_path, dimensions=4) as store:
            results = store.query([1.0, 0.0, 0.0, 0.0], top_k=5)
            assert results == []

    def test_context_manager(self, tmp_path):
        store_path = tmp_path / "test.zvec"
        with ZvecDocumentStore(store_path, dimensions=4) as store:
            store.add_documents(
                texts=["test"],
                embeddings=[[1.0, 0.0, 0.0, 0.0]],
                sources=["t.txt"],
            )
        # After close, dir should still exist
        assert store_path.exists()

    def test_query_with_exact_source_filter(self, tmp_path):
        store_path = tmp_path / "test.zvec"
        with ZvecDocumentStore(store_path, dimensions=4) as store:
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
        store_path = tmp_path / "test.zvec"
        with ZvecDocumentStore(store_path, dimensions=4) as store:
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
        store_path = tmp_path / "test.zvec"
        with ZvecDocumentStore(store_path, dimensions=4) as store:
            store.add_documents(
                texts=["hello"],
                embeddings=[[1.0, 0.0, 0.0, 0.0]],
                sources=["a.txt"],
            )
            results = store.query([1.0, 0.0, 0.0, 0.0], top_k=5, source_filter="b.txt")
            assert results == []

    def test_add_documents_with_ingested_at(self, tmp_path):
        store_path = tmp_path / "test.zvec"
        with ZvecDocumentStore(store_path, dimensions=4) as store:
            store.add_documents(
                texts=["hello"],
                embeddings=[[1.0, 0.0, 0.0, 0.0]],
                sources=["a.txt"],
                ingested_at="2025-01-01T00:00:00",
            )
            # Verify via query
            results = store.query([1.0, 0.0, 0.0, 0.0], top_k=1)
            assert len(results) == 1
            assert results[0].source == "a.txt"

    def test_file_metadata_upsert_and_get(self, tmp_path):
        store_path = tmp_path / "test.zvec"
        with ZvecDocumentStore(store_path, dimensions=4) as store:
            store.upsert_file_metadata("a.txt", "abc123", 1000.0, "2025-01-01T00:00:00", 5)
            meta = store.get_file_metadata("a.txt")
            assert meta is not None
            assert meta[0] == "abc123"
            assert meta[1] == 1000.0
            assert meta[2] == "2025-01-01T00:00:00"

    def test_file_metadata_overwrite(self, tmp_path):
        store_path = tmp_path / "test.zvec"
        with ZvecDocumentStore(store_path, dimensions=4) as store:
            store.upsert_file_metadata("a.txt", "hash1", 1000.0, "2025-01-01", 5)
            store.upsert_file_metadata("a.txt", "hash2", 2000.0, "2025-02-01", 10)
            meta = store.get_file_metadata("a.txt")
            assert meta is not None
            assert meta[0] == "hash2"
            assert meta[1] == 2000.0
            assert meta[2] == "2025-02-01"

    def test_file_metadata_get_nonexistent(self, tmp_path):
        store_path = tmp_path / "test.zvec"
        with ZvecDocumentStore(store_path, dimensions=4) as store:
            assert store.get_file_metadata("nonexistent.txt") is None

    def test_file_metadata_delete(self, tmp_path):
        store_path = tmp_path / "test.zvec"
        with ZvecDocumentStore(store_path, dimensions=4) as store:
            store.upsert_file_metadata("a.txt", "hash1", 1000.0, "2025-01-01", 5)
            store.delete_file_metadata("a.txt")
            assert store.get_file_metadata("a.txt") is None

    def test_list_sources(self, tmp_path):
        store_path = tmp_path / "test.zvec"
        with ZvecDocumentStore(store_path, dimensions=4) as store:
            store.upsert_file_metadata("a.txt", "h1", 1.0, "t1", 1)
            store.upsert_file_metadata("b.txt", "h2", 2.0, "t2", 2)
            sources = store.list_sources()
            assert sorted(sources) == ["a.txt", "b.txt"]

    def test_replace_source(self, tmp_path):
        store_path = tmp_path / "test.zvec"
        with ZvecDocumentStore(store_path, dimensions=4) as store:
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

    def test_store_meta_read_write(self, tmp_path):
        store_path = tmp_path / "test.zvec"
        with ZvecDocumentStore(store_path, dimensions=4) as store:
            assert store.read_store_meta("nonexistent") is None
            store.write_store_meta("my_key", "my_value")
            assert store.read_store_meta("my_key") == "my_value"
