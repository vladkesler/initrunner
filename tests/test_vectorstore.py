"""Tests for the vector store."""

import pytest

from initrunner.stores.lance_document_store import _FTS_INDEX_NAME
from initrunner.stores.lance_store import LanceDocumentStore


class TestLanceDocumentStore:
    def test_create_store(self, tmp_path):
        store_path = tmp_path / "test.lance"
        with LanceDocumentStore(store_path, dimensions=4):
            assert store_path.exists()

    def test_shared_id_counter_across_instances(self, tmp_path):
        """Regression (F1): two stores opened on the same path share one ID
        counter, so a second instance does not restart allocation at 1."""
        store_path = tmp_path / "shared.lance"
        s1 = LanceDocumentStore(store_path, dimensions=4)
        s2 = LanceDocumentStore(store_path, dimensions=4)
        try:
            a = s1._alloc_ids(3)
            b = s2._alloc_ids(3)
            assert set(a).isdisjoint(b)  # before the fix s2 restarted at 1
            assert min(b) == max(a) + 1
        finally:
            s1.close()
            s2.close()

    def test_concurrent_instances_no_duplicate_chunk_ids(self, tmp_path):
        """Regression (F1): concurrent writers on one path (retrieval tool,
        web_scraper, ingestion service) must not produce duplicate chunk IDs."""
        store_path = tmp_path / "shared_docs.lance"
        vec = [1.0, 0.0, 0.0, 0.0]
        s1 = LanceDocumentStore(store_path, dimensions=4)
        s2 = LanceDocumentStore(store_path, dimensions=4)
        try:
            s1.add_documents(["a", "b"], [vec, vec], ["s1", "s1"])
            s2.add_documents(["c", "d"], [vec, vec], ["s2", "s2"])
            ids = [r.chunk_id for r in s1.query(vec, top_k=10)]
            assert len(ids) == 4
            assert len(set(ids)) == 4  # all unique -- no overlapping ranges
        finally:
            s1.close()
            s2.close()

    def test_add_and_count(self, tmp_path):
        store_path = tmp_path / "test.lance"
        with LanceDocumentStore(store_path, dimensions=4) as store:
            store.add_documents(
                texts=["hello world", "foo bar"],
                embeddings=[[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0]],
                sources=["a.txt", "b.txt"],
            )
            assert store.count() == 2

    def test_query(self, tmp_path):
        store_path = tmp_path / "test.lance"
        with LanceDocumentStore(store_path, dimensions=4) as store:
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
        store_path = tmp_path / "test.lance"
        with LanceDocumentStore(store_path, dimensions=4) as store:
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
        store_path = tmp_path / "test.lance"
        with LanceDocumentStore(store_path, dimensions=4) as store:
            results = store.query([1.0, 0.0, 0.0, 0.0], top_k=5)
            assert results == []

    def test_context_manager(self, tmp_path):
        store_path = tmp_path / "test.lance"
        with LanceDocumentStore(store_path, dimensions=4) as store:
            store.add_documents(
                texts=["test"],
                embeddings=[[1.0, 0.0, 0.0, 0.0]],
                sources=["t.txt"],
            )
        # After close, dir should still exist
        assert store_path.exists()

    def test_query_with_exact_source_filter(self, tmp_path):
        store_path = tmp_path / "test.lance"
        with LanceDocumentStore(store_path, dimensions=4) as store:
            store.add_documents(
                texts=["hello world", "foo bar", "baz qux"],
                embeddings=[
                    [1.0, 0.0, 0.0, 0.0],
                    [0.9, 0.1, 0.0, 0.0],
                    [0.0, 0.0, 1.0, 0.0],
                ],
                sources=["a.txt", "b.txt", "a.txt"],
            )
            # Filter to only a.txt -- should return both a.txt chunks
            results = store.query([1.0, 0.0, 0.0, 0.0], top_k=5, source_filter="a.txt")
            assert all(r.source == "a.txt" for r in results)
            assert len(results) == 2

    def test_query_with_glob_filter(self, tmp_path):
        store_path = tmp_path / "test.lance"
        with LanceDocumentStore(store_path, dimensions=4) as store:
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
        store_path = tmp_path / "test.lance"
        with LanceDocumentStore(store_path, dimensions=4) as store:
            store.add_documents(
                texts=["hello"],
                embeddings=[[1.0, 0.0, 0.0, 0.0]],
                sources=["a.txt"],
            )
            results = store.query([1.0, 0.0, 0.0, 0.0], top_k=5, source_filter="b.txt")
            assert results == []

    def test_add_documents_with_ingested_at(self, tmp_path):
        store_path = tmp_path / "test.lance"
        with LanceDocumentStore(store_path, dimensions=4) as store:
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
        store_path = tmp_path / "test.lance"
        with LanceDocumentStore(store_path, dimensions=4) as store:
            store.upsert_file_metadata("a.txt", "abc123", 1000.0, "2025-01-01T00:00:00", 5)
            meta = store.get_file_metadata("a.txt")
            assert meta is not None
            assert meta[0] == "abc123"
            assert meta[1] == 1000.0
            assert meta[2] == "2025-01-01T00:00:00"

    def test_file_metadata_overwrite(self, tmp_path):
        store_path = tmp_path / "test.lance"
        with LanceDocumentStore(store_path, dimensions=4) as store:
            store.upsert_file_metadata("a.txt", "hash1", 1000.0, "2025-01-01", 5)
            store.upsert_file_metadata("a.txt", "hash2", 2000.0, "2025-02-01", 10)
            meta = store.get_file_metadata("a.txt")
            assert meta is not None
            assert meta[0] == "hash2"
            assert meta[1] == 2000.0
            assert meta[2] == "2025-02-01"

    def test_file_metadata_get_nonexistent(self, tmp_path):
        store_path = tmp_path / "test.lance"
        with LanceDocumentStore(store_path, dimensions=4) as store:
            assert store.get_file_metadata("nonexistent.txt") is None

    def test_file_metadata_delete(self, tmp_path):
        store_path = tmp_path / "test.lance"
        with LanceDocumentStore(store_path, dimensions=4) as store:
            store.upsert_file_metadata("a.txt", "hash1", 1000.0, "2025-01-01", 5)
            store.delete_file_metadata("a.txt")
            assert store.get_file_metadata("a.txt") is None

    def test_list_sources(self, tmp_path):
        store_path = tmp_path / "test.lance"
        with LanceDocumentStore(store_path, dimensions=4) as store:
            store.upsert_file_metadata("a.txt", "h1", 1.0, "t1", 1)
            store.upsert_file_metadata("b.txt", "h2", 2.0, "t2", 2)
            sources = store.list_sources()
            assert sorted(sources) == ["a.txt", "b.txt"]

    def test_replace_source(self, tmp_path):
        store_path = tmp_path / "test.lance"
        with LanceDocumentStore(store_path, dimensions=4) as store:
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
        store_path = tmp_path / "test.lance"
        with LanceDocumentStore(store_path, dimensions=4) as store:
            assert store.read_store_meta("nonexistent") is None
            store.write_store_meta("my_key", "my_value")
            assert store.read_store_meta("my_key") == "my_value"


def _seed_corpus(store: LanceDocumentStore) -> None:
    store.add_documents(
        texts=[
            "python programming language",
            "machine learning models",
            "data science with python",
        ],
        embeddings=[
            [1.0, 0.0, 0.0, 0.0],
            [0.0, 1.0, 0.0, 0.0],
            [0.0, 0.0, 1.0, 0.0],
        ],
        sources=["a.md", "b.md", "c.md"],
    )


class TestHybridSearch:
    def test_fts_index_created_on_first_add(self, tmp_path):
        store_path = tmp_path / "test.lance"
        with LanceDocumentStore(store_path, dimensions=4) as store:
            assert store._fts_ready is False
            _seed_corpus(store)
            assert store._fts_ready is True
            tbl = store._db.open_table("chunks")
            assert _FTS_INDEX_NAME in {ix.name for ix in tbl.list_indices()}

    def test_hybrid_search_basic(self, tmp_path):
        store_path = tmp_path / "test.lance"
        with LanceDocumentStore(store_path, dimensions=4) as store:
            _seed_corpus(store)
            results = store.hybrid_search(
                "python",
                [1.0, 0.0, 0.0, 0.0],
                top_k=2,
                retrieval_strategy="hybrid",
            )
            assert len(results) == 2
            top_sources = {r.source for r in results}
            # both python-containing docs should rank in the top 2
            assert "a.md" in top_sources

    def test_hybrid_search_fts_surfaces_keyword(self, tmp_path):
        store_path = tmp_path / "test.lance"
        with LanceDocumentStore(store_path, dimensions=4) as store:
            store.add_documents(
                texts=["API reference", "REST endpoints", "GraphQL schema"],
                embeddings=[
                    [0.0, 0.0, 0.0, 1.0],
                    [0.0, 1.0, 0.0, 0.0],
                    [0.0, 0.0, 1.0, 0.0],
                ],
                sources=["api.md", "rest.md", "graphql.md"],
            )
            # vector query points away from the API doc, but the keyword matches
            results = store.hybrid_search(
                "API",
                [0.0, 1.0, 0.0, 0.0],
                top_k=3,
                retrieval_strategy="hybrid",
            )
            assert any(r.source == "api.md" for r in results)

    def test_hybrid_search_with_glob_filter(self, tmp_path):
        store_path = tmp_path / "test.lance"
        with LanceDocumentStore(store_path, dimensions=4) as store:
            store.add_documents(
                texts=["python guide", "python api", "python blog"],
                embeddings=[
                    [1.0, 0.0, 0.0, 0.0],
                    [0.0, 1.0, 0.0, 0.0],
                    [0.0, 0.0, 1.0, 0.0],
                ],
                sources=["docs/guide.md", "docs/api.md", "blog/post.txt"],
            )
            results = store.hybrid_search(
                "python",
                [1.0, 0.0, 0.0, 0.0],
                top_k=5,
                retrieval_strategy="hybrid",
                source_filter="docs/*",
            )
            assert results
            assert all(r.source.startswith("docs/") for r in results)

    def test_hybrid_search_with_exact_filter(self, tmp_path):
        store_path = tmp_path / "test.lance"
        with LanceDocumentStore(store_path, dimensions=4) as store:
            _seed_corpus(store)
            results = store.hybrid_search(
                "python",
                [1.0, 0.0, 0.0, 0.0],
                top_k=5,
                retrieval_strategy="hybrid",
                source_filter="a.md",
            )
            assert [r.source for r in results] == ["a.md"]

    def test_vector_strategy_matches_query(self, tmp_path):
        store_path = tmp_path / "test.lance"
        with LanceDocumentStore(store_path, dimensions=4) as store:
            _seed_corpus(store)
            via_query = store.query([1.0, 0.0, 0.0, 0.0], top_k=3)
            via_hybrid = store.hybrid_search(
                "python",
                [1.0, 0.0, 0.0, 0.0],
                top_k=3,
                retrieval_strategy="vector",
            )
            assert [r.chunk_id for r in via_query] == [r.chunk_id for r in via_hybrid]
            assert [r.distance for r in via_query] == [r.distance for r in via_hybrid]

    def test_empty_text_falls_back_to_vector(self, tmp_path):
        store_path = tmp_path / "test.lance"
        with LanceDocumentStore(store_path, dimensions=4) as store:
            _seed_corpus(store)
            results = store.hybrid_search(
                "   ",
                [1.0, 0.0, 0.0, 0.0],
                top_k=2,
                retrieval_strategy="hybrid",
            )
            # blank text means no BM25 signal; results come from dense search
            assert results[0].source == "a.md"

    def test_hybrid_search_empty_store(self, tmp_path):
        store_path = tmp_path / "test.lance"
        with LanceDocumentStore(store_path, dimensions=4) as store:
            results = store.hybrid_search(
                "python",
                [1.0, 0.0, 0.0, 0.0],
                retrieval_strategy="hybrid",
            )
            assert results == []

    def test_unknown_strategy_raises(self, tmp_path):
        store_path = tmp_path / "test.lance"
        with LanceDocumentStore(store_path, dimensions=4) as store:
            _seed_corpus(store)
            with pytest.raises(ValueError, match="Unknown retrieval_strategy"):
                store.hybrid_search(
                    "python",
                    [1.0, 0.0, 0.0, 0.0],
                    retrieval_strategy="bogus",
                )

    def test_hybrid_rerank_degrades_without_backend(self, tmp_path, monkeypatch):
        # Force the cross-encoder import to fail so the reranker degrades to RRF.
        import lancedb.rerankers

        class _Boom:
            def __init__(self, *args, **kwargs):
                raise ImportError("no torch")

        monkeypatch.setattr(lancedb.rerankers, "CrossEncoderReranker", _Boom)
        store_path = tmp_path / "test.lance"
        with LanceDocumentStore(store_path, dimensions=4) as store:
            _seed_corpus(store)
            results = store.hybrid_search(
                "python",
                [1.0, 0.0, 0.0, 0.0],
                top_k=2,
                retrieval_strategy="hybrid_rerank",
            )
            assert len(results) == 2

    def test_hybrid_rerank_cross_encoder(self, tmp_path):
        pytest.importorskip("sentence_transformers")
        store_path = tmp_path / "test.lance"
        with LanceDocumentStore(store_path, dimensions=4) as store:
            _seed_corpus(store)
            results = store.hybrid_search(
                "python",
                [1.0, 0.0, 0.0, 0.0],
                top_k=2,
                retrieval_strategy="hybrid_rerank",
            )
            assert len(results) == 2
            assert any("python" in r.text for r in results)
