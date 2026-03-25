"""Tests for the ingestion manifest module."""

from __future__ import annotations

import json

from initrunner.ingestion.manifest import (
    ManagedSource,
    add_to_manifest,
    read_manifest,
    read_manifest_json,
    remove_from_manifest,
    serialize_manifest,
    uploads_dir,
    write_manifest,
)

# ---------------------------------------------------------------------------
# Fake store (dict-backed)
# ---------------------------------------------------------------------------


class FakeStore:
    def __init__(self):
        self._meta: dict[str, str] = {}

    def read_store_meta(self, key: str) -> str | None:
        return self._meta.get(key)

    def write_store_meta(self, key: str, value: str) -> None:
        self._meta[key] = value


# ---------------------------------------------------------------------------
# read_manifest_json
# ---------------------------------------------------------------------------


class TestReadManifestJson:
    def test_none_returns_empty(self):
        assert read_manifest_json(None) == []

    def test_empty_string_returns_empty(self):
        assert read_manifest_json("") == []

    def test_invalid_json_returns_empty(self):
        assert read_manifest_json("not-json{{{") == []

    def test_valid_json(self):
        payload = json.dumps(
            [
                {"path": "/tmp/a.txt", "source_type": "file", "added_at": "2026-01-01T00:00:00"},
                {"path": "https://example.com", "source_type": "url", "added_at": "2026-01-02"},
            ]
        )
        result = read_manifest_json(payload)
        assert len(result) == 2
        assert result[0].path == "/tmp/a.txt"
        assert result[0].source_type == "file"
        assert result[1].source_type == "url"

    def test_skips_non_dict_entries(self):
        payload = json.dumps(
            [
                {"path": "/tmp/a.txt", "source_type": "file", "added_at": "2026-01-01"},
                "bad-entry",
                42,
            ]
        )
        result = read_manifest_json(payload)
        assert len(result) == 1


# ---------------------------------------------------------------------------
# serialize_manifest / round-trip
# ---------------------------------------------------------------------------


class TestSerializeManifest:
    def test_round_trip(self):
        sources = [
            ManagedSource(path="/tmp/a.txt", source_type="file", added_at="2026-01-01"),
            ManagedSource(path="https://x.com", source_type="url", added_at="2026-01-02"),
        ]
        raw = serialize_manifest(sources)
        restored = read_manifest_json(raw)
        assert len(restored) == 2
        assert restored[0].path == "/tmp/a.txt"
        assert restored[1].path == "https://x.com"

    def test_empty(self):
        assert serialize_manifest([]) == "[]"


# ---------------------------------------------------------------------------
# read_manifest / write_manifest (store integration)
# ---------------------------------------------------------------------------


class TestReadWriteManifest:
    def test_read_empty_store(self):
        store = FakeStore()
        assert read_manifest(store) == []  # type: ignore[arg-type]

    def test_write_then_read(self):
        store = FakeStore()
        sources = [ManagedSource(path="/a", source_type="file", added_at="2026-01-01")]
        write_manifest(store, sources)  # type: ignore[arg-type]
        result = read_manifest(store)  # type: ignore[arg-type]
        assert len(result) == 1
        assert result[0].path == "/a"


# ---------------------------------------------------------------------------
# add_to_manifest (deduplication)
# ---------------------------------------------------------------------------


class TestAddToManifest:
    def test_adds_new_entries(self):
        store = FakeStore()
        entries = [
            ManagedSource(path="/a.txt", source_type="file", added_at="2026-01-01"),
            ManagedSource(path="/b.txt", source_type="file", added_at="2026-01-01"),
        ]
        result = add_to_manifest(store, entries)  # type: ignore[arg-type]
        assert len(result) == 2

    def test_deduplicates_by_path(self):
        store = FakeStore()
        first = [ManagedSource(path="/a.txt", source_type="file", added_at="2026-01-01")]
        add_to_manifest(store, first)  # type: ignore[arg-type]

        dupe = [
            ManagedSource(path="/a.txt", source_type="file", added_at="2026-02-01"),
            ManagedSource(path="/c.txt", source_type="file", added_at="2026-02-01"),
        ]
        result = add_to_manifest(store, dupe)  # type: ignore[arg-type]
        assert len(result) == 2
        paths = {s.path for s in result}
        assert paths == {"/a.txt", "/c.txt"}

    def test_deduplicates_within_single_call(self):
        store = FakeStore()
        entries = [
            ManagedSource(path="/a.txt", source_type="file", added_at="2026-01-01"),
            ManagedSource(path="/a.txt", source_type="file", added_at="2026-01-02"),
        ]
        result = add_to_manifest(store, entries)  # type: ignore[arg-type]
        assert len(result) == 1


# ---------------------------------------------------------------------------
# remove_from_manifest
# ---------------------------------------------------------------------------


class TestRemoveFromManifest:
    def test_removes_existing(self):
        store = FakeStore()
        entries = [
            ManagedSource(path="/a.txt", source_type="file", added_at="2026-01-01"),
            ManagedSource(path="/b.txt", source_type="file", added_at="2026-01-01"),
        ]
        add_to_manifest(store, entries)  # type: ignore[arg-type]

        result = remove_from_manifest(store, "/a.txt")  # type: ignore[arg-type]
        assert len(result) == 1
        assert result[0].path == "/b.txt"

    def test_noop_when_not_found(self):
        store = FakeStore()
        entries = [ManagedSource(path="/a.txt", source_type="file", added_at="2026-01-01")]
        add_to_manifest(store, entries)  # type: ignore[arg-type]

        # Should not write back (same length)
        original_raw = store._meta.get("managed_sources")
        result = remove_from_manifest(store, "/nonexistent.txt")  # type: ignore[arg-type]
        assert len(result) == 1
        # Meta value unchanged -- write_manifest was not called
        assert store._meta.get("managed_sources") == original_raw

    def test_removes_from_empty_manifest(self):
        store = FakeStore()
        result = remove_from_manifest(store, "/anything")  # type: ignore[arg-type]
        assert result == []


# ---------------------------------------------------------------------------
# uploads_dir
# ---------------------------------------------------------------------------


class TestUploadsDir:
    def test_creates_directory(self, tmp_path, monkeypatch):
        monkeypatch.setattr("initrunner.config.get_home_dir", lambda: tmp_path)
        d = uploads_dir("my-agent")
        assert d.is_dir()
        assert d == tmp_path / "uploads" / "my-agent"

    def test_idempotent(self, tmp_path, monkeypatch):
        monkeypatch.setattr("initrunner.config.get_home_dir", lambda: tmp_path)
        d1 = uploads_dir("my-agent")
        d2 = uploads_dir("my-agent")
        assert d1 == d2
