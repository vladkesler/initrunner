"""End-to-end tests for incremental ingestion."""

from unittest.mock import MagicMock, patch

import pytest

from initrunner.agent.schema import ChunkingConfig, EmbeddingConfig, IngestConfig
from initrunner.ingestion.pipeline import FileStatus, run_ingest
from initrunner.stores.sqlite_vec import SqliteVecDocumentStore as SqliteVecStore


def _make_config(sources=None):
    return IngestConfig(
        sources=sources or ["*.txt"],
        chunking=ChunkingConfig(strategy="fixed", chunk_size=512, chunk_overlap=0),
        embeddings=EmbeddingConfig(),
    )


async def _fake_embed(embedder, texts, **kwargs):
    """Return deterministic 4-dim vectors."""
    return [[float(i % 4 == j) for j in range(4)] for i in range(len(texts))]


@pytest.fixture()
def ingest_env(tmp_path):
    """Set up a patched environment for incremental ingest tests."""
    store_path = tmp_path / "store.db"
    mock_embedder = MagicMock()

    patches = [
        patch("initrunner.ingestion.pipeline.create_embedder", return_value=mock_embedder),
        patch("initrunner.ingestion.pipeline.embed_texts", new=_fake_embed),
        patch(
            "initrunner.ingestion.pipeline._get_store_path",
            return_value=store_path,
        ),
    ]
    for p in patches:
        p.start()
    yield tmp_path, store_path
    for p in patches:
        p.stop()


class TestIncrementalIngest:
    def test_first_run_all_new(self, ingest_env):
        tmp_path, _ = ingest_env
        (tmp_path / "a.txt").write_text("hello world")
        (tmp_path / "b.txt").write_text("foo bar baz")

        stats = run_ingest(_make_config(), "test", base_dir=tmp_path)
        assert stats.new == 2
        assert stats.skipped == 0
        assert stats.updated == 0
        assert stats.total_chunks > 0

    def test_unchanged_files_skipped(self, ingest_env):
        tmp_path, store_path = ingest_env
        (tmp_path / "a.txt").write_text("hello world")
        (tmp_path / "b.txt").write_text("foo bar baz")

        # First run
        stats1 = run_ingest(_make_config(), "test", base_dir=tmp_path)
        assert stats1.new == 2

        # Second run — same files, should be skipped
        stats2 = run_ingest(_make_config(), "test", base_dir=tmp_path)
        assert stats2.skipped == 2
        assert stats2.new == 0
        assert stats2.updated == 0

        # Chunk count should be unchanged
        with SqliteVecStore(store_path, dimensions=4) as store:
            assert store.count() == stats1.total_chunks

    def test_modified_file_updated(self, ingest_env):
        tmp_path, _ = ingest_env
        (tmp_path / "a.txt").write_text("original content")

        stats1 = run_ingest(_make_config(), "test", base_dir=tmp_path)
        assert stats1.new == 1

        # Modify file
        (tmp_path / "a.txt").write_text("modified content that is different")

        stats2 = run_ingest(_make_config(), "test", base_dir=tmp_path)
        assert stats2.updated == 1
        assert stats2.new == 0
        assert stats2.skipped == 0

    def test_force_reprocesses(self, ingest_env):
        tmp_path, _ = ingest_env
        (tmp_path / "a.txt").write_text("hello world")

        # First run
        run_ingest(_make_config(), "test", base_dir=tmp_path)

        # Force re-ingest — should not skip
        stats = run_ingest(_make_config(), "test", base_dir=tmp_path, force=True)
        assert stats.new == 1
        assert stats.skipped == 0

    def test_error_tracked(self, ingest_env):
        tmp_path, _ = ingest_env
        (tmp_path / "a.txt").write_text("hello")

        # Make file unreadable by using extract_text patch
        with patch(
            "initrunner.ingestion.pipeline.extract_text",
            side_effect=OSError("Permission denied"),
        ):
            stats = run_ingest(_make_config(), "test", base_dir=tmp_path)

        assert stats.errored == 1
        assert stats.new == 0
        error_results = [r for r in stats.file_results if r.status == FileStatus.ERROR]
        assert len(error_results) == 1
        assert error_results[0].error is not None and "Permission denied" in error_results[0].error

    def test_stats_counts_correct(self, ingest_env):
        tmp_path, _ = ingest_env
        (tmp_path / "a.txt").write_text("file a content")
        (tmp_path / "b.txt").write_text("file b content")
        (tmp_path / "c.txt").write_text("file c content")

        # First run: all new
        run_ingest(_make_config(), "test", base_dir=tmp_path)

        # Modify one, keep two
        (tmp_path / "b.txt").write_text("modified b content different")

        stats2 = run_ingest(_make_config(), "test", base_dir=tmp_path)
        assert stats2.new == 0
        assert stats2.updated == 1
        assert stats2.skipped == 2
        assert stats2.errored == 0
        # file_results should have 3 entries
        assert len(stats2.file_results) == 3

    def test_deleted_file_purged(self, ingest_env):
        tmp_path, store_path = ingest_env
        (tmp_path / "a.txt").write_text("file a")
        (tmp_path / "b.txt").write_text("file b")

        stats1 = run_ingest(_make_config(), "test", base_dir=tmp_path)
        assert stats1.new == 2

        # Delete b.txt
        (tmp_path / "b.txt").unlink()

        stats2 = run_ingest(_make_config(), "test", base_dir=tmp_path)
        # a should be skipped (unchanged), b purged from DB
        assert stats2.skipped == 1
        assert stats2.new == 0

        # Verify b.txt metadata and chunks are gone
        with SqliteVecStore(store_path, dimensions=4) as store:
            assert store.get_file_metadata(str(tmp_path / "b.txt")) is None
            sources = store.list_sources()
            assert str(tmp_path / "b.txt") not in sources

    def test_no_files_returns_empty_stats(self, ingest_env):
        tmp_path, _ = ingest_env
        stats = run_ingest(_make_config(["*.xyz"]), "test", base_dir=tmp_path)
        assert stats.new == 0
        assert stats.total_chunks == 0
        assert stats.file_results == []
