"""Tests for the dashboard ingestion router endpoints."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("fastapi", reason="dashboard extras not installed")

from fastapi.testclient import TestClient  # type: ignore[import-not-found]

from initrunner.agent.schema.base import ApiVersion, Kind, ModelConfig, RoleMetadata
from initrunner.agent.schema.ingestion import IngestConfig
from initrunner.agent.schema.role import AgentSpec, RoleDefinition
from initrunner.dashboard.app import create_app
from initrunner.dashboard.config import DashboardSettings
from initrunner.dashboard.deps import RoleCache, get_role_cache
from initrunner.services.ingestion import IngestedDocument, IngestSummaryInfo


@dataclass
class FakeDiscoveredRole:
    path: Path
    role: RoleDefinition | None = None
    error: str | None = None


def _make_role() -> RoleDefinition:
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
    return RoleDefinition(
        apiVersion=ApiVersion.V1,
        kind=Kind.AGENT,
        metadata=RoleMetadata(name="test-agent"),
        spec=AgentSpec(
            role="You are a test agent.",
            model=ModelConfig(provider="openai", name="gpt-4o"),
        ),
    )


@pytest.fixture()
def client_and_cache():
    """Create a TestClient with a mock RoleCache injected."""
    mock_cache = MagicMock(spec=RoleCache)

    with (
        patch("initrunner.dashboard.app.RoleCache", return_value=mock_cache),
        patch("initrunner.dashboard.app.FlowCache"),
        patch("initrunner.dashboard.app.TeamCache"),
    ):
        app = create_app(DashboardSettings())

    app.dependency_overrides[get_role_cache] = lambda: mock_cache
    client = TestClient(app, raise_server_exceptions=False)
    return client, mock_cache


# ---------------------------------------------------------------------------
# GET /api/agents/{agent_id}/ingest/documents
# ---------------------------------------------------------------------------


class TestListDocuments:
    def test_returns_404_for_unknown_agent(self, client_and_cache):
        client, cache = client_and_cache
        cache.get.return_value = None
        resp = client.get("/api/agents/unknown-id/ingest/documents")
        assert resp.status_code == 404

    def test_returns_400_when_no_ingest_config(self, client_and_cache):
        client, cache = client_and_cache
        dr = FakeDiscoveredRole(path=Path("/tmp/role.yaml"), role=_make_role_no_ingest())
        cache.get.return_value = dr
        resp = client.get("/api/agents/some-id/ingest/documents")
        assert resp.status_code == 400

    @patch("initrunner.services.ingestion.list_ingested_documents_sync")
    def test_returns_document_list(self, mock_list, client_and_cache):
        client, cache = client_and_cache
        dr = FakeDiscoveredRole(path=Path("/tmp/role.yaml"), role=_make_role())
        cache.get.return_value = dr

        mock_list.return_value = [
            IngestedDocument(
                source="file.txt",
                chunk_count=5,
                ingested_at="2026-01-01",
                content_hash="abc",
                last_modified=1000.0,
                is_managed=False,
            ),
            IngestedDocument(
                source="https://example.com",
                chunk_count=3,
                ingested_at="2026-01-02",
                content_hash="def",
                last_modified=2000.0,
                is_managed=True,
            ),
        ]

        resp = client.get("/api/agents/agent-id/ingest/documents")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        assert data[0]["source"] == "file.txt"
        assert data[0]["is_managed"] is False
        assert data[0]["is_url"] is False
        assert data[1]["source"] == "https://example.com"
        assert data[1]["is_managed"] is True
        assert data[1]["is_url"] is True


# ---------------------------------------------------------------------------
# GET /api/agents/{agent_id}/ingest/summary
# ---------------------------------------------------------------------------


class TestIngestSummary:
    @patch("initrunner.services.ingestion.get_ingest_summary_sync")
    def test_returns_summary(self, mock_summary, client_and_cache):
        client, cache = client_and_cache
        dr = FakeDiscoveredRole(path=Path("/tmp/role.yaml"), role=_make_role())
        cache.get.return_value = dr

        mock_summary.return_value = IngestSummaryInfo(
            total_documents=10,
            total_chunks=50,
            store_path="/store.lance",
            sources_config=["*.txt"],
            managed_count=2,
            last_ingested_at="2026-01-05",
        )

        resp = client.get("/api/agents/agent-id/ingest/summary")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_documents"] == 10
        assert data["total_chunks"] == 50
        assert data["managed_count"] == 2
        assert data["last_ingested_at"] == "2026-01-05"


# ---------------------------------------------------------------------------
# DELETE /api/agents/{agent_id}/ingest/documents
# ---------------------------------------------------------------------------


class TestDeleteDocument:
    def test_returns_404_for_unknown_agent(self, client_and_cache):
        client, cache = client_and_cache
        cache.get.return_value = None
        resp = client.delete("/api/agents/unknown/ingest/documents?source=file.txt")
        assert resp.status_code == 404

    @patch("initrunner.services.ingestion.delete_ingested_source_sync")
    def test_deletes_source(self, mock_delete, client_and_cache):
        client, cache = client_and_cache
        dr = FakeDiscoveredRole(path=Path("/tmp/role.yaml"), role=_make_role())
        cache.get.return_value = dr
        mock_delete.return_value = 7

        resp = client.delete("/api/agents/agent-id/ingest/documents?source=file.txt")
        assert resp.status_code == 200
        data = resp.json()
        assert data["chunks_deleted"] == 7
        mock_delete.assert_called_once()


# ---------------------------------------------------------------------------
# POST /api/agents/{agent_id}/ingest/add-url
# ---------------------------------------------------------------------------


class TestAddUrl:
    def test_returns_404_for_unknown_agent(self, client_and_cache):
        client, cache = client_and_cache
        cache.get.return_value = None
        resp = client.post(
            "/api/agents/unknown/ingest/add-url", json={"url": "https://example.com"}
        )
        assert resp.status_code == 404

    @patch("initrunner.services.ingestion.run_ingest_managed_sync")
    def test_triggers_managed_ingest(self, mock_ingest, client_and_cache):
        client, cache = client_and_cache
        dr = FakeDiscoveredRole(path=Path("/tmp/role.yaml"), role=_make_role())
        cache.get.return_value = dr

        mock_stats = MagicMock()
        mock_stats.new = 1
        mock_stats.updated = 0
        mock_stats.skipped = 0
        mock_stats.errored = 0
        mock_stats.total_chunks = 5
        mock_stats.file_results = []
        mock_ingest.return_value = mock_stats

        resp = client.post(
            "/api/agents/agent-id/ingest/add-url", json={"url": "https://example.com"}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["new"] == 1
        assert data["total_chunks"] == 5

    @patch("initrunner.services.ingestion.run_ingest_managed_sync")
    def test_returns_400_when_ingest_returns_none(self, mock_ingest, client_and_cache):
        client, cache = client_and_cache
        dr = FakeDiscoveredRole(path=Path("/tmp/role.yaml"), role=_make_role())
        cache.get.return_value = dr
        mock_ingest.return_value = None

        resp = client.post(
            "/api/agents/agent-id/ingest/add-url", json={"url": "https://example.com"}
        )
        assert resp.status_code == 400

    def test_rejects_file_scheme(self, client_and_cache):
        client, cache = client_and_cache
        dr = FakeDiscoveredRole(path=Path("/tmp/role.yaml"), role=_make_role())
        cache.get.return_value = dr
        resp = client.post(
            "/api/agents/agent-id/ingest/add-url", json={"url": "file:///etc/passwd"}
        )
        assert resp.status_code == 422

    def test_rejects_ftp_scheme(self, client_and_cache):
        client, cache = client_and_cache
        dr = FakeDiscoveredRole(path=Path("/tmp/role.yaml"), role=_make_role())
        cache.get.return_value = dr
        resp = client.post(
            "/api/agents/agent-id/ingest/add-url", json={"url": "ftp://evil.com/data"}
        )
        assert resp.status_code == 422

    def test_rejects_no_hostname(self, client_and_cache):
        client, cache = client_and_cache
        dr = FakeDiscoveredRole(path=Path("/tmp/role.yaml"), role=_make_role())
        cache.get.return_value = dr
        resp = client.post("/api/agents/agent-id/ingest/add-url", json={"url": "http://"})
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# POST /api/agents/{agent_id}/ingest/upload -- path traversal
# ---------------------------------------------------------------------------


class TestUploadPathTraversal:
    @patch("initrunner.services.ingestion.run_ingest_managed_sync")
    @patch("initrunner.ingestion.manifest.uploads_dir")
    def test_traversal_filename_stripped_to_basename(
        self, mock_uploads_dir, mock_ingest, client_and_cache, tmp_path
    ):
        """A filename with ../ components should be stripped to its basename."""
        client, cache = client_and_cache
        dr = FakeDiscoveredRole(path=Path("/tmp/role.yaml"), role=_make_role())
        cache.get.return_value = dr

        upload_dir = tmp_path / "uploads"
        upload_dir.mkdir()
        mock_uploads_dir.return_value = upload_dir

        mock_stats = MagicMock()
        mock_stats.new = 1
        mock_stats.updated = 0
        mock_stats.skipped = 0
        mock_stats.errored = 0
        mock_stats.total_chunks = 1
        mock_stats.file_results = []
        mock_ingest.return_value = mock_stats

        resp = client.post(
            "/api/agents/agent-id/ingest/upload",
            files=[("files", ("../../evil.txt", b"malicious content", "text/plain"))],
        )
        assert resp.status_code == 200
        # File should be saved as just "evil.txt" in the upload dir
        assert (upload_dir / "evil.txt").exists()
        # No file should exist outside the upload dir
        assert not (tmp_path / "evil.txt").exists()


# ---------------------------------------------------------------------------
# DELETE path traversal
# ---------------------------------------------------------------------------


class TestDeletePathTraversal:
    def test_traversal_path_not_deleted(self, tmp_path):
        """delete_ingested_source_sync must not delete files outside uploads dir."""
        from initrunner.services.ingestion import delete_ingested_source_sync

        upload_dir = tmp_path / "uploads"
        upload_dir.mkdir()

        # Create a file outside the uploads dir
        outside_file = tmp_path / "secret.txt"
        outside_file.write_text("sensitive")

        role = _make_role()

        with (
            patch("initrunner.services.ingestion._open_doc_store") as mock_store,
            patch("initrunner.ingestion.manifest.remove_from_manifest"),
            patch("initrunner.ingestion.manifest.uploads_dir", return_value=upload_dir),
        ):
            mock_ctx = MagicMock()
            mock_ctx.__enter__ = MagicMock(return_value=mock_ctx)
            mock_ctx.__exit__ = MagicMock(return_value=False)
            mock_ctx.delete_by_source.return_value = 0
            mock_store.return_value = (mock_ctx, tmp_path / "store.lance")

            delete_ingested_source_sync(role, str(outside_file))

        # The file outside uploads dir must NOT be deleted
        assert outside_file.exists()
