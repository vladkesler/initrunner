"""Tests for LanceDocumentStore.list_all_file_metadata()."""

from __future__ import annotations

from initrunner.stores.lance_store import LanceDocumentStore


def test_list_all_file_metadata_empty(tmp_path):
    store = LanceDocumentStore(tmp_path / "test.lance", dimensions=8)
    assert store.list_all_file_metadata() == []
    store.close()


def test_list_all_file_metadata_with_data(tmp_path):
    store = LanceDocumentStore(tmp_path / "test.lance", dimensions=8)
    store.upsert_file_metadata("file1.txt", "hash1", 1000.0, "2026-01-01T00:00:00", 5)
    store.upsert_file_metadata("file2.txt", "hash2", 2000.0, "2026-01-02T00:00:00", 3)
    rows = store.list_all_file_metadata()
    assert len(rows) == 2
    sources = {r[0] for r in rows}
    assert sources == {"file1.txt", "file2.txt"}
    # Each tuple: (source, content_hash, last_modified, ingested_at, chunk_count)
    for row in rows:
        assert len(row) == 5
    store.close()


def test_list_all_file_metadata_tuple_fields(tmp_path):
    store = LanceDocumentStore(tmp_path / "test.lance", dimensions=8)
    store.upsert_file_metadata("doc.md", "abc123", 9999.0, "2026-03-15T12:00:00", 42)
    rows = store.list_all_file_metadata()
    assert len(rows) == 1
    source, content_hash, last_modified, ingested_at, chunk_count = rows[0]
    assert source == "doc.md"
    assert content_hash == "abc123"
    assert last_modified == 9999.0
    assert ingested_at == "2026-03-15T12:00:00"
    assert chunk_count == 42
    store.close()


def test_upsert_updates_existing(tmp_path):
    store = LanceDocumentStore(tmp_path / "test.lance", dimensions=8)
    store.upsert_file_metadata("file.txt", "hash-v1", 1000.0, "2026-01-01", 5)
    store.upsert_file_metadata("file.txt", "hash-v2", 2000.0, "2026-01-02", 10)
    rows = store.list_all_file_metadata()
    assert len(rows) == 1
    _source, content_hash, _lm, _ia, chunk_count = rows[0]
    assert content_hash == "hash-v2"
    assert chunk_count == 10
    store.close()


def test_list_all_after_delete(tmp_path):
    store = LanceDocumentStore(tmp_path / "test.lance", dimensions=8)
    store.upsert_file_metadata("keep.txt", "h1", 1000.0, "2026-01-01", 5)
    store.upsert_file_metadata("remove.txt", "h2", 2000.0, "2026-01-02", 3)
    store.delete_file_metadata("remove.txt")
    rows = store.list_all_file_metadata()
    assert len(rows) == 1
    assert rows[0][0] == "keep.txt"
    store.close()


def test_store_meta_round_trip(tmp_path):
    """Verify read_store_meta/write_store_meta used by manifest module."""
    store = LanceDocumentStore(tmp_path / "test.lance", dimensions=8)
    assert store.read_store_meta("missing") is None
    store.write_store_meta("my_key", "my_value")
    assert store.read_store_meta("my_key") == "my_value"
    store.close()
