"""Tests for the ingestion pipeline (source resolution + chunking + hashing)."""

from pathlib import Path

from initrunner.ingestion.pipeline import (
    FileStatus,
    IngestStats,
    _content_hash,
    _file_hash,
    _is_url,
    resolve_sources,
)


class TestIsUrl:
    def test_http(self):
        assert _is_url("http://example.com") is True

    def test_https(self):
        assert _is_url("https://example.com/path") is True

    def test_glob(self):
        assert _is_url("*.txt") is False

    def test_relative_path(self):
        assert _is_url("docs/file.md") is False


class TestResolveSources:
    def test_glob_txt(self, tmp_path):
        (tmp_path / "a.txt").write_text("hello")
        (tmp_path / "b.txt").write_text("world")
        (tmp_path / "c.md").write_text("markdown")
        files, urls = resolve_sources(["*.txt"], base_dir=tmp_path)
        assert len(files) == 2
        assert all(f.suffix == ".txt" for f in files)
        assert urls == []

    def test_recursive_glob(self, tmp_path):
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "a.md").write_text("hello")
        files, urls = resolve_sources(["**/*.md"], base_dir=tmp_path)
        assert len(files) == 1
        assert urls == []

    def test_no_matches(self, tmp_path):
        files, urls = resolve_sources(["*.xyz"], base_dir=tmp_path)
        assert files == []
        assert urls == []

    def test_deduplication(self, tmp_path):
        (tmp_path / "a.txt").write_text("hello")
        files, urls = resolve_sources(["*.txt", "a.txt"], base_dir=tmp_path)
        assert len(files) == 1
        assert urls == []

    def test_mixed_files_and_urls(self, tmp_path):
        (tmp_path / "a.txt").write_text("hello")
        sources = ["*.txt", "https://example.com/page", "http://other.com/doc"]
        files, urls = resolve_sources(sources, base_dir=tmp_path)
        assert len(files) == 1
        assert len(urls) == 2
        assert "https://example.com/page" in urls
        assert "http://other.com/doc" in urls

    def test_urls_only(self):
        files, urls = resolve_sources(["https://example.com/a", "https://example.com/b"])
        assert files == []
        assert len(urls) == 2


class TestFileHash:
    def test_deterministic(self, tmp_path):
        f = tmp_path / "a.txt"
        f.write_text("hello world")
        h1 = _file_hash(f)
        h2 = _file_hash(f)
        assert h1 == h2
        assert len(h1) == 64  # SHA-256 hex

    def test_changes_with_content(self, tmp_path):
        f = tmp_path / "a.txt"
        f.write_text("hello")
        h1 = _file_hash(f)
        f.write_text("world")
        h2 = _file_hash(f)
        assert h1 != h2


class TestContentHash:
    def test_deterministic(self):
        h1 = _content_hash("hello world")
        h2 = _content_hash("hello world")
        assert h1 == h2
        assert len(h1) == 64

    def test_changes_with_content(self):
        h1 = _content_hash("hello")
        h2 = _content_hash("world")
        assert h1 != h2


class TestIngestStats:
    def test_defaults(self):
        stats = IngestStats()
        assert stats.new == 0
        assert stats.updated == 0
        assert stats.skipped == 0
        assert stats.errored == 0
        assert stats.total_chunks == 0
        assert stats.file_results == []

    def test_accumulation(self):
        stats = IngestStats(new=2, updated=1, skipped=3, errored=1, total_chunks=10)
        assert stats.new + stats.updated == 3


class TestProgressCallback:
    def test_callback_called(self, tmp_path, monkeypatch):
        """Verify progress_callback is invoked per file with mocked embedder."""
        from unittest.mock import MagicMock, patch

        from initrunner.agent.schema import ChunkingConfig, EmbeddingConfig, IngestConfig

        # Create test files
        (tmp_path / "a.txt").write_text("hello world content here")
        (tmp_path / "b.txt").write_text("another file with content")

        config = IngestConfig(
            sources=["*.txt"],
            chunking=ChunkingConfig(strategy="fixed", chunk_size=512, chunk_overlap=0),
            embeddings=EmbeddingConfig(),
        )

        # Mock the embedder to return deterministic 4-dim vectors
        mock_embedder = MagicMock()

        async def fake_embed(emb, texts, **kw):
            return [[1.0, 0.0, 0.0, 0.0]] * len(texts)

        callback_calls: list[tuple[Path, FileStatus]] = []

        def callback(path, status):
            callback_calls.append((path, status))

        with (
            patch("initrunner.ingestion.pipeline.create_embedder", return_value=mock_embedder),
            patch("initrunner.ingestion.pipeline.embed_texts", new=fake_embed),
            patch(
                "initrunner.ingestion.pipeline._get_store_path",
                return_value=tmp_path / "store.db",
            ),
        ):
            from initrunner.ingestion.pipeline import run_ingest

            stats = run_ingest(
                config,
                "test-agent",
                base_dir=tmp_path,
                progress_callback=callback,
            )

        assert len(callback_calls) == 2
        assert stats.new == 2
        assert all(status == FileStatus.NEW for _, status in callback_calls)


class TestUrlClassification:
    def test_classify_urls_new(self, tmp_path):
        """URLs not in metadata are classified as NEW."""
        from unittest.mock import patch

        from initrunner.ingestion.pipeline import _classify_urls

        def fake_extract(url, **kw):
            return f"Content from {url}"

        stats = IngestStats()
        with patch("initrunner.ingestion.extractors.extract_url", side_effect=fake_extract):
            to_process, resolved = _classify_urls(
                ["https://example.com/page"],
                {},
                stats,
                force=False,
                progress_callback=None,
            )

        assert len(to_process) == 1
        url, status, text = to_process[0]
        assert url == "https://example.com/page"
        assert status == FileStatus.NEW
        assert "Content from" in text
        assert "https://example.com/page" in resolved

    def test_classify_urls_skipped(self, tmp_path):
        """URLs with unchanged content hash are SKIPPED."""
        from unittest.mock import patch

        from initrunner.ingestion.pipeline import _classify_urls, _content_hash

        content = "Same content"

        def fake_extract(url, **kw):
            return content

        existing_hash = _content_hash(content)
        file_metadata = {"https://example.com/page": existing_hash}

        stats = IngestStats()
        with patch("initrunner.ingestion.extractors.extract_url", side_effect=fake_extract):
            to_process, _resolved = _classify_urls(
                ["https://example.com/page"],
                file_metadata,
                stats,
                force=False,
                progress_callback=None,
            )

        assert len(to_process) == 0
        assert stats.skipped == 1

    def test_classify_urls_error_handled(self):
        """URLs that fail to fetch are recorded as errors."""
        from unittest.mock import patch

        from initrunner.ingestion.pipeline import _classify_urls

        def fake_extract(url, **kw):
            raise ConnectionError("connection refused")

        stats = IngestStats()
        with patch("initrunner.ingestion.extractors.extract_url", side_effect=fake_extract):
            to_process, _resolved = _classify_urls(
                ["https://down.example.com"],
                {},
                stats,
                force=False,
                progress_callback=None,
            )

        assert len(to_process) == 0
        assert stats.errored == 1

    def test_classify_urls_force(self):
        """Force mode classifies all as NEW regardless of hash."""
        from unittest.mock import patch

        from initrunner.ingestion.pipeline import _classify_urls, _content_hash

        content = "Same content"

        def fake_extract(url, **kw):
            return content

        existing_hash = _content_hash(content)
        file_metadata = {"https://example.com/page": existing_hash}

        stats = IngestStats()
        with patch("initrunner.ingestion.extractors.extract_url", side_effect=fake_extract):
            to_process, _resolved = _classify_urls(
                ["https://example.com/page"],
                file_metadata,
                stats,
                force=True,
                progress_callback=None,
            )

        assert len(to_process) == 1
        assert to_process[0][1] == FileStatus.NEW
