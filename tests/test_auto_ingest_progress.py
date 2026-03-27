"""Tests for auto-ingest progress: accurate totals and callback invocation."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from initrunner.agent.schema.base import ApiVersion, Kind, ModelConfig, RoleMetadata
from initrunner.agent.schema.ingestion import ChunkingConfig, EmbeddingConfig, IngestConfig
from initrunner.agent.schema.role import AgentSpec, RoleDefinition
from initrunner.ingestion.pipeline import FileStatus, resolve_full_sources


def _make_role(
    tmp_path: Path,
    *,
    auto: bool = True,
    sources: list[str] | None = None,
) -> RoleDefinition:
    return RoleDefinition(
        apiVersion=ApiVersion.V1,
        kind=Kind.AGENT,
        metadata=RoleMetadata(name="test-ingest-agent"),
        spec=AgentSpec(
            role="You are a test.",
            model=ModelConfig(provider="openai", name="gpt-5-mini"),
            ingest=IngestConfig(
                sources=sources or ["*.txt"],
                auto=auto,
                chunking=ChunkingConfig(strategy="fixed", chunk_size=512, chunk_overlap=0),
                embeddings=EmbeddingConfig(),
            ),
        ),
    )


class TestResolveFullSources:
    def test_includes_glob_sources(self, tmp_path):
        (tmp_path / "a.txt").write_text("hello")
        (tmp_path / "b.txt").write_text("world")
        config = IngestConfig(
            sources=["*.txt"],
            chunking=ChunkingConfig(strategy="fixed", chunk_size=512, chunk_overlap=0),
            embeddings=EmbeddingConfig(),
        )
        files, _urls = resolve_full_sources(config, "test-agent", base_dir=tmp_path)
        assert len(files) == 2

    def test_includes_managed_sources(self, tmp_path):
        """Managed sources from the manifest should be included in the total."""
        config = IngestConfig(
            sources=["*.txt"],
            chunking=ChunkingConfig(strategy="fixed", chunk_size=512, chunk_overlap=0),
            embeddings=EmbeddingConfig(),
        )
        (tmp_path / "a.txt").write_text("hello")
        # Place managed file outside the glob base so it's only from the manifest
        uploads = tmp_path / "uploads"
        uploads.mkdir()
        managed_file = uploads / "managed.txt"
        managed_file.write_text("managed content")

        with patch(
            "initrunner.ingestion.pipeline._merge_managed_sources",
            return_value=([managed_file], ["https://example.com/doc"]),
        ):
            files, urls = resolve_full_sources(config, "test-agent", base_dir=tmp_path)

        assert len(files) == 2  # a.txt + managed.txt
        assert len(urls) == 1  # managed URL
        assert managed_file in files


class TestResolveAutoIngestTotal:
    def test_returns_total_when_store_empty(self, tmp_path):
        from initrunner.services.ingest import resolve_auto_ingest_total

        (tmp_path / "a.txt").write_text("hello")
        (tmp_path / "b.txt").write_text("world")

        role = _make_role(tmp_path)
        role_file = tmp_path / "role.yaml"
        role_file.write_text("")

        with patch("initrunner.services.ingest.is_store_populated", return_value=False):
            total = resolve_auto_ingest_total(role, role_file)

        assert total == 2

    def test_returns_none_when_store_populated(self, tmp_path):
        from initrunner.services.ingest import resolve_auto_ingest_total

        (tmp_path / "a.txt").write_text("hello")

        role = _make_role(tmp_path)
        role_file = tmp_path / "role.yaml"
        role_file.write_text("")

        with patch("initrunner.services.ingest.is_store_populated", return_value=True):
            total = resolve_auto_ingest_total(role, role_file)

        assert total is None

    def test_returns_none_when_auto_disabled(self, tmp_path):
        from initrunner.services.ingest import resolve_auto_ingest_total

        role = _make_role(tmp_path, auto=False)
        role_file = tmp_path / "role.yaml"
        role_file.write_text("")

        total = resolve_auto_ingest_total(role, role_file)
        assert total is None

    def test_returns_none_when_no_ingest_config(self, tmp_path):
        from initrunner.services.ingest import resolve_auto_ingest_total

        role = RoleDefinition(
            apiVersion=ApiVersion.V1,
            kind=Kind.AGENT,
            metadata=RoleMetadata(name="no-ingest-agent"),
            spec=AgentSpec(
                role="You are a test.",
                model=ModelConfig(provider="openai", name="gpt-5-mini"),
            ),
        )
        role_file = tmp_path / "role.yaml"
        role_file.write_text("")

        total = resolve_auto_ingest_total(role, role_file)
        assert total is None


class TestAutoIngestProgressCallback:
    def test_callback_count_matches_total(self, tmp_path):
        """Progress callback should fire exactly resolve_auto_ingest_total times."""
        from initrunner.services.ingest import auto_ingest_if_needed, resolve_auto_ingest_total

        (tmp_path / "a.txt").write_text("hello world content here")
        (tmp_path / "b.txt").write_text("another file with content")

        role = _make_role(tmp_path)
        role_file = tmp_path / "role.yaml"
        role_file.write_text("")

        mock_embedder = MagicMock()

        async def fake_embed(emb, texts, **kw):
            return [[1.0, 0.0, 0.0, 0.0]] * len(texts)

        with (
            patch("initrunner.services.ingest.is_store_populated", return_value=False),
            patch("initrunner.ingestion.pipeline.create_embedder", return_value=mock_embedder),
            patch("initrunner.ingestion.pipeline.embed_texts", new=fake_embed),
            patch(
                "initrunner.ingestion.pipeline._get_store_path",
                return_value=tmp_path / "store.db",
            ),
        ):
            total = resolve_auto_ingest_total(role, role_file)

            callback_calls: list[tuple[Path, FileStatus]] = []

            def on_progress(path: Path, status: FileStatus) -> None:
                callback_calls.append((path, status))

            stats = auto_ingest_if_needed(role, role_file, progress_callback=on_progress)

        assert total is not None
        assert len(callback_calls) == total
        assert stats is not None
        assert stats.new == 2
