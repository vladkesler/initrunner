"""Tests for run_ingest_managed and _merge_managed_sources in the pipeline."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from initrunner.agent.schema.ingestion import IngestConfig
from initrunner.ingestion.manifest import ManagedSource
from initrunner.ingestion.pipeline import (
    FileResult,
    FileStatus,
    IngestStats,
    _merge_managed_sources,
    run_ingest_managed,
)


def _make_config() -> IngestConfig:
    return IngestConfig(sources=["*.txt"])


# ---------------------------------------------------------------------------
# _merge_managed_sources
# ---------------------------------------------------------------------------


class TestMergeManagedSources:
    @patch("initrunner.ingestion.pipeline._get_store_path")
    def test_returns_empty_when_store_does_not_exist(self, mock_store_path, tmp_path):
        mock_store_path.return_value = tmp_path / "nonexistent.lance"
        files, urls = _merge_managed_sources(_make_config(), "agent")
        assert files == []
        assert urls == []

    @patch("initrunner.ingestion.pipeline.create_document_store")
    @patch("initrunner.ingestion.pipeline._get_store_path")
    def test_returns_files_and_urls(self, mock_store_path, mock_factory, tmp_path):
        db_path = tmp_path / "store.lance"
        db_path.mkdir()
        mock_store_path.return_value = db_path

        mock_store = MagicMock()
        mock_store.__enter__ = MagicMock(return_value=mock_store)
        mock_store.__exit__ = MagicMock(return_value=False)
        mock_factory.return_value = mock_store

        file_path = tmp_path / "managed.txt"
        file_path.write_text("content")

        with patch(
            "initrunner.ingestion.manifest.read_manifest",
            return_value=[
                ManagedSource(path=str(file_path), source_type="file", added_at="2026-01-01"),
                ManagedSource(path="https://example.com", source_type="url", added_at="2026-01-02"),
            ],
        ):
            files, urls = _merge_managed_sources(_make_config(), "agent")

        assert len(files) == 1
        assert files[0] == file_path
        assert urls == ["https://example.com"]

    @patch("initrunner.ingestion.pipeline.create_document_store")
    @patch("initrunner.ingestion.pipeline._get_store_path")
    def test_skips_missing_files(self, mock_store_path, mock_factory, tmp_path):
        db_path = tmp_path / "store.lance"
        db_path.mkdir()
        mock_store_path.return_value = db_path

        mock_store = MagicMock()
        mock_store.__enter__ = MagicMock(return_value=mock_store)
        mock_store.__exit__ = MagicMock(return_value=False)
        mock_factory.return_value = mock_store

        with patch(
            "initrunner.ingestion.manifest.read_manifest",
            return_value=[
                ManagedSource(
                    path="/nonexistent/file.txt", source_type="file", added_at="2026-01-01"
                ),
            ],
        ):
            files, _urls = _merge_managed_sources(_make_config(), "agent")

        assert files == []


# ---------------------------------------------------------------------------
# run_ingest_managed
# ---------------------------------------------------------------------------


class TestRunIngestManaged:
    @patch("initrunner.ingestion.manifest.add_to_manifest")
    @patch("initrunner.ingestion.pipeline.create_document_store")
    @patch("initrunner.ingestion.pipeline._get_store_path")
    @patch("initrunner.ingestion.pipeline._execute_ingest_core")
    def test_adds_successful_files_to_manifest(
        self, mock_core, mock_store_path, mock_factory, mock_add
    ):
        fake_stats = IngestStats(new=1, total_chunks=5)
        fake_stats.file_results = [
            FileResult(path=Path("/tmp/f.txt"), status=FileStatus.NEW, chunks=5)
        ]
        mock_core.return_value = fake_stats

        db_path = MagicMock(spec=Path)
        db_path.exists.return_value = True
        mock_store_path.return_value = db_path

        mock_store = MagicMock()
        mock_store.__enter__ = MagicMock(return_value=mock_store)
        mock_store.__exit__ = MagicMock(return_value=False)
        mock_factory.return_value = mock_store

        stats = run_ingest_managed(
            files=[Path("/tmp/f.txt")],
            urls=[],
            config=_make_config(),
            agent_name="test",
        )

        assert stats.new == 1
        assert stats.total_chunks == 5
        mock_add.assert_called_once()
        entries = mock_add.call_args[0][1]
        assert len(entries) == 1
        assert entries[0].path == "/tmp/f.txt"
        assert entries[0].source_type == "file"

    @patch("initrunner.ingestion.manifest.add_to_manifest")
    @patch("initrunner.ingestion.pipeline._get_store_path")
    @patch("initrunner.ingestion.pipeline._execute_ingest_core")
    def test_does_not_add_errored_files(self, mock_core, mock_store_path, mock_add):
        fake_stats = IngestStats(errored=1)
        fake_stats.file_results = [
            FileResult(
                path=Path("/tmp/bad.txt"),
                status=FileStatus.ERROR,
                error="extraction failed",
            )
        ]
        mock_core.return_value = fake_stats

        db_path = MagicMock(spec=Path)
        db_path.exists.return_value = True
        mock_store_path.return_value = db_path

        stats = run_ingest_managed(
            files=[Path("/tmp/bad.txt")],
            urls=[],
            config=_make_config(),
            agent_name="test",
        )

        assert stats.errored == 1
        mock_add.assert_not_called()

    @patch("initrunner.ingestion.manifest.add_to_manifest")
    @patch("initrunner.ingestion.pipeline.create_document_store")
    @patch("initrunner.ingestion.pipeline._get_store_path")
    @patch("initrunner.ingestion.pipeline._execute_ingest_core")
    def test_adds_urls_to_manifest(self, mock_core, mock_store_path, mock_factory, mock_add):
        # Use a mock for the path field so str(path) returns the raw URL
        # (Path normalizes "https://..." to "https:/..." which breaks the lookup).
        mock_path = MagicMock()
        mock_path.__str__ = lambda _self: "https://example.com"

        fake_stats = IngestStats(new=1, total_chunks=3)
        fake_stats.file_results = [FileResult(path=mock_path, status=FileStatus.NEW, chunks=3)]
        mock_core.return_value = fake_stats

        db_path = MagicMock(spec=Path)
        db_path.exists.return_value = True
        mock_store_path.return_value = db_path

        mock_store = MagicMock()
        mock_store.__enter__ = MagicMock(return_value=mock_store)
        mock_store.__exit__ = MagicMock(return_value=False)
        mock_factory.return_value = mock_store

        stats = run_ingest_managed(
            files=[],
            urls=["https://example.com"],
            config=_make_config(),
            agent_name="test",
        )

        assert stats.new == 1
        mock_add.assert_called_once()
        entries = mock_add.call_args[0][1]
        assert len(entries) == 1
        assert entries[0].path == "https://example.com"
        assert entries[0].source_type == "url"

    @patch("initrunner.ingestion.pipeline._get_store_path")
    @patch("initrunner.ingestion.pipeline._execute_ingest_core")
    def test_skips_manifest_write_when_store_missing(self, mock_core, mock_store_path):
        """If the store does not exist after ingest (e.g. all files errored), skip manifest."""
        fake_stats = IngestStats(errored=1)
        fake_stats.file_results = [
            FileResult(path=Path("/tmp/bad.txt"), status=FileStatus.ERROR, error="fail")
        ]
        mock_core.return_value = fake_stats

        db_path = MagicMock(spec=Path)
        db_path.exists.return_value = False
        mock_store_path.return_value = db_path

        stats = run_ingest_managed(
            files=[Path("/tmp/bad.txt")],
            urls=[],
            config=_make_config(),
            agent_name="test",
        )
        assert stats.errored == 1

    @patch("initrunner.ingestion.pipeline._get_store_path")
    @patch("initrunner.ingestion.pipeline._execute_ingest_core")
    def test_no_files_returns_empty_stats(self, mock_core, mock_store_path):
        mock_core.return_value = IngestStats()
        mock_store_path.return_value = MagicMock(spec=Path)

        stats = run_ingest_managed(
            files=[],
            urls=[],
            config=_make_config(),
            agent_name="test",
        )
        assert stats.new == 0
        assert stats.total_chunks == 0
