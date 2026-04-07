"""Tests for `resolve_full_sources` source-merging behavior.

The auto-ingest plan and progress UI tests live in
``tests/test_auto_ingest_stale.py``; this file is now scoped to the source
resolution helper alone.
"""

from unittest.mock import patch

from initrunner.agent.schema.ingestion import ChunkingConfig, EmbeddingConfig, IngestConfig
from initrunner.ingestion.pipeline import resolve_full_sources


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
