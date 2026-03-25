"""Tests for initrunner.services.ingestion -- the sync service layer."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from initrunner.agent.schema.base import ApiVersion, Kind, ModelConfig, RoleMetadata
from initrunner.agent.schema.ingestion import IngestConfig
from initrunner.agent.schema.role import AgentSpec, RoleDefinition
from initrunner.ingestion.manifest import ManagedSource
from initrunner.services.ingestion import (
    delete_ingested_source_sync,
    get_ingest_summary_sync,
    list_ingested_documents_sync,
)


def _make_role() -> RoleDefinition:
    """Create a minimal RoleDefinition with ingest config."""
    return RoleDefinition(
        apiVersion=ApiVersion.V1,
        kind=Kind.AGENT,
        metadata=RoleMetadata(name="test-agent"),
        spec=AgentSpec(
            role="You are a test agent.",
            model=ModelConfig(provider="openai", name="gpt-4o"),
            ingest=IngestConfig(sources=["*.txt"]),
        ),
    )


def _make_role_no_ingest() -> RoleDefinition:
    """Create a RoleDefinition without ingest config."""
    return RoleDefinition(
        apiVersion=ApiVersion.V1,
        kind=Kind.AGENT,
        metadata=RoleMetadata(name="test-agent"),
        spec=AgentSpec(
            role="You are a test agent.",
            model=ModelConfig(provider="openai", name="gpt-4o"),
        ),
    )


# ---------------------------------------------------------------------------
# list_ingested_documents_sync
# ---------------------------------------------------------------------------


class TestListIngestedDocuments:
    def test_returns_empty_when_no_ingest_config(self):
        role = _make_role_no_ingest()
        result = list_ingested_documents_sync(role)
        assert result == []

    @patch("initrunner.services.ingestion._open_doc_store")
    def test_returns_empty_when_store_does_not_exist(self, mock_open):
        mock_open.return_value = (None, Path("/fake/store.lance"))
        role = _make_role()
        result = list_ingested_documents_sync(role)
        assert result == []

    @patch("initrunner.services.ingestion._open_doc_store")
    def test_returns_documents_with_managed_flag(self, mock_open):
        mock_store = MagicMock()
        mock_store.__enter__ = MagicMock(return_value=mock_store)
        mock_store.__exit__ = MagicMock(return_value=False)
        mock_store.list_all_file_metadata.return_value = [
            ("file1.txt", "hash1", 1000.0, "2026-01-01", 5),
            ("https://example.com", "hash2", 2000.0, "2026-01-02", 3),
        ]

        mock_open.return_value = (mock_store, Path("/fake/store.lance"))

        with patch(
            "initrunner.ingestion.manifest.read_manifest",
            return_value=[
                ManagedSource(path="https://example.com", source_type="url", added_at="2026-01-02")
            ],
        ):
            role = _make_role()
            result = list_ingested_documents_sync(role)

        assert len(result) == 2
        # file1.txt is not managed
        assert result[0].source == "file1.txt"
        assert result[0].is_managed is False
        assert result[0].chunk_count == 5
        # URL is managed
        assert result[1].source == "https://example.com"
        assert result[1].is_managed is True
        assert result[1].chunk_count == 3


# ---------------------------------------------------------------------------
# get_ingest_summary_sync
# ---------------------------------------------------------------------------


class TestGetIngestSummary:
    def test_returns_zeros_when_no_ingest_config(self):
        role = _make_role_no_ingest()
        info = get_ingest_summary_sync(role)
        assert info.total_documents == 0
        assert info.total_chunks == 0
        assert info.managed_count == 0

    @patch("initrunner.services.ingestion._open_doc_store")
    def test_returns_zeros_when_store_not_found(self, mock_open):
        mock_open.return_value = (None, Path("/fake/store.lance"))
        role = _make_role()
        info = get_ingest_summary_sync(role)
        assert info.total_documents == 0
        assert info.total_chunks == 0
        assert info.store_path == "/fake/store.lance"

    @patch("initrunner.services.ingestion._open_doc_store")
    def test_returns_correct_aggregates(self, mock_open):
        mock_store = MagicMock()
        mock_store.__enter__ = MagicMock(return_value=mock_store)
        mock_store.__exit__ = MagicMock(return_value=False)
        mock_store.list_all_file_metadata.return_value = [
            ("file1.txt", "h1", 1000.0, "2026-01-01", 5),
            ("file2.txt", "h2", 2000.0, "2026-01-05", 3),
        ]
        mock_store.count.return_value = 8
        mock_open.return_value = (mock_store, Path("/store.lance"))

        with patch(
            "initrunner.ingestion.manifest.read_manifest",
            return_value=[
                ManagedSource(path="file1.txt", source_type="file", added_at="2026-01-01")
            ],
        ):
            role = _make_role()
            info = get_ingest_summary_sync(role)

        assert info.total_documents == 2
        assert info.total_chunks == 8
        assert info.managed_count == 1
        assert info.last_ingested_at == "2026-01-05"
        assert info.store_path == "/store.lance"
        assert info.sources_config == ["*.txt"]


# ---------------------------------------------------------------------------
# delete_ingested_source_sync
# ---------------------------------------------------------------------------


class TestDeleteIngestedSource:
    @patch("initrunner.services.ingestion._open_doc_store")
    def test_returns_zero_when_store_not_found(self, mock_open):
        mock_open.return_value = (None, None)
        role = _make_role()
        assert delete_ingested_source_sync(role, "file.txt") == 0

    @patch("initrunner.ingestion.manifest.uploads_dir")
    @patch("initrunner.services.ingestion._open_doc_store")
    def test_deletes_from_store_and_manifest(self, mock_open, mock_uploads_dir, tmp_path):
        mock_store = MagicMock()
        mock_store.__enter__ = MagicMock(return_value=mock_store)
        mock_store.__exit__ = MagicMock(return_value=False)
        mock_store.delete_by_source.return_value = 5
        mock_open.return_value = (mock_store, Path("/store.lance"))
        mock_uploads_dir.return_value = tmp_path / "uploads"

        role = _make_role()
        deleted = delete_ingested_source_sync(role, "doc.txt")

        assert deleted == 5
        mock_store.delete_by_source.assert_called_once_with("doc.txt")
        mock_store.delete_file_metadata.assert_called_once_with("doc.txt")

    @patch("initrunner.ingestion.manifest.uploads_dir")
    @patch("initrunner.services.ingestion._open_doc_store")
    def test_cleans_up_uploaded_file(self, mock_open, mock_uploads_dir, tmp_path):
        upload_dir = tmp_path / "uploads"
        upload_dir.mkdir(parents=True)
        target = upload_dir / "uploaded.txt"
        target.write_text("content")

        mock_store = MagicMock()
        mock_store.__enter__ = MagicMock(return_value=mock_store)
        mock_store.__exit__ = MagicMock(return_value=False)
        mock_store.delete_by_source.return_value = 1
        mock_open.return_value = (mock_store, Path("/store.lance"))
        mock_uploads_dir.return_value = upload_dir

        role = _make_role()
        delete_ingested_source_sync(role, str(target))

        assert not target.exists()
