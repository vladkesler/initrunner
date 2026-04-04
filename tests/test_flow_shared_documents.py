"""Tests for shared document stores in flows."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from initrunner.agent.schema.base import ApiVersion, Kind, ModelConfig, RoleMetadata
from initrunner.agent.schema.ingestion import ChunkingConfig, EmbeddingConfig, IngestConfig
from initrunner.agent.schema.role import AgentSpec, RoleDefinition
from initrunner.flow.orchestrator import apply_shared_documents
from initrunner.flow.schema import (
    FlowAgentConfig,
    FlowDefinition,
    FlowSpec,
    SharedDocumentsConfig,
)
from initrunner.stores.base import StoreBackend


def _make_role(*, ingest: IngestConfig | None = None) -> RoleDefinition:
    return RoleDefinition(
        apiVersion=ApiVersion.V1,
        kind=Kind.AGENT,
        metadata=RoleMetadata(name="test-agent"),
        spec=AgentSpec(
            role="You are a test.",
            model=ModelConfig(provider="openai", name="gpt-5-mini"),
            ingest=ingest,
        ),
    )


class TestSharedDocumentsConfig:
    def test_defaults(self):
        cfg = SharedDocumentsConfig()
        assert cfg.enabled is False
        assert cfg.store_path is None
        assert cfg.store_backend == StoreBackend.LANCEDB
        assert cfg.embeddings.provider == ""
        assert cfg.embeddings.model == ""

    def test_enabled_requires_embeddings_provider(self):
        with pytest.raises(
            ValidationError, match=r"shared_documents\.embeddings\.provider is required"
        ):
            SharedDocumentsConfig(
                enabled=True,
                embeddings=EmbeddingConfig(model="text-embedding-3-small"),
            )

    def test_enabled_requires_embeddings_model(self):
        with pytest.raises(
            ValidationError, match=r"shared_documents\.embeddings\.model is required"
        ):
            SharedDocumentsConfig(
                enabled=True,
                embeddings=EmbeddingConfig(provider="openai"),
            )

    def test_enabled_with_full_embeddings(self):
        cfg = SharedDocumentsConfig(
            enabled=True,
            embeddings=EmbeddingConfig(provider="openai", model="text-embedding-3-small"),
        )
        assert cfg.enabled is True
        assert cfg.embeddings.provider == "openai"
        assert cfg.embeddings.model == "text-embedding-3-small"

    def test_disabled_does_not_require_embeddings(self):
        cfg = SharedDocumentsConfig(enabled=False)
        assert cfg.embeddings.provider == ""


class TestApplySharedDocuments:
    def test_with_existing_ingest(self):
        role = _make_role(
            ingest=IngestConfig(
                sources=["docs/"],
                chunking=ChunkingConfig(chunk_size=256, chunk_overlap=32),
                embeddings=EmbeddingConfig(provider="google", model="text-embedding-004"),
                store_path="/old/path.lance",
            )
        )

        cfg = SharedDocumentsConfig(
            enabled=True,
            embeddings=EmbeddingConfig(provider="openai", model="text-embedding-3-small"),
        )

        apply_shared_documents(role, cfg, "/shared/docs.lance")

        assert role.spec.ingest is not None
        assert role.spec.ingest.store_path == "/shared/docs.lance"
        assert role.spec.ingest.store_backend == StoreBackend.LANCEDB
        assert role.spec.ingest.embeddings.provider == "openai"
        assert role.spec.ingest.embeddings.model == "text-embedding-3-small"
        # Preserved fields
        assert role.spec.ingest.sources == ["docs/"]
        assert role.spec.ingest.chunking.chunk_size == 256

    def test_without_ingest(self):
        role = _make_role()
        assert role.spec.ingest is None

        cfg = SharedDocumentsConfig(
            enabled=True,
            embeddings=EmbeddingConfig(provider="openai", model="text-embedding-3-small"),
        )

        apply_shared_documents(role, cfg, "/shared/docs.lance")

        assert role.spec.ingest is not None
        assert role.spec.ingest.sources == []
        assert role.spec.ingest.store_path == "/shared/docs.lance"
        assert role.spec.ingest.embeddings.provider == "openai"
        assert role.spec.ingest.embeddings.model == "text-embedding-3-small"


class TestFlowSpecWithSharedDocuments:
    def test_flow_spec_with_shared_documents(self):
        spec = FlowSpec(
            agents={
                "researcher": FlowAgentConfig(role="researcher.yaml"),
                "writer": FlowAgentConfig(role="writer.yaml"),
            },
            shared_documents=SharedDocumentsConfig(
                enabled=True,
                store_path="/tmp/shared.lance",
                embeddings=EmbeddingConfig(provider="openai", model="text-embedding-3-small"),
            ),
        )
        assert spec.shared_documents.enabled is True
        assert spec.shared_documents.store_path == "/tmp/shared.lance"

    def test_flow_definition_with_shared_documents(self):
        data = {
            "apiVersion": "initrunner/v1",
            "kind": "Flow",
            "metadata": {"name": "test-flow"},
            "spec": {
                "agents": {
                    "a": {"role": "a.yaml"},
                    "b": {"role": "b.yaml"},
                },
                "shared_documents": {
                    "enabled": True,
                    "embeddings": {
                        "provider": "openai",
                        "model": "text-embedding-3-small",
                    },
                },
            },
        }
        defn = FlowDefinition.model_validate(data)
        assert defn.spec.shared_documents.enabled is True
        assert defn.spec.shared_documents.embeddings.provider == "openai"


class TestBuildMembersWiresSharedDocuments:
    @patch("initrunner.flow.orchestrator.resolve_role_model", side_effect=lambda r, *a, **kw: r)
    @patch("initrunner.flow.orchestrator.build_agent")
    @patch("initrunner.flow.orchestrator.load_role")
    @patch("initrunner.flow.orchestrator._load_dotenv")
    def test_build_members_wires_shared_documents(
        self, mock_dotenv, mock_load_role, mock_build_agent, _mock_resolve, tmp_path
    ):
        role = _make_role()
        mock_load_role.return_value = role
        mock_build_agent.return_value = MagicMock()

        # Create dummy role files
        roles_dir = tmp_path / "roles"
        roles_dir.mkdir()
        (roles_dir / "a.yaml").write_text("")

        flow_data = {
            "apiVersion": "initrunner/v1",
            "kind": "Flow",
            "metadata": {"name": "test-flow"},
            "spec": {
                "agents": {
                    "a": {"role": "roles/a.yaml"},
                },
                "shared_documents": {
                    "enabled": True,
                    "store_path": "/tmp/shared.lance",
                    "embeddings": {
                        "provider": "openai",
                        "model": "text-embedding-3-small",
                    },
                },
            },
        }

        from initrunner.flow.orchestrator import FlowOrchestrator

        flow = FlowDefinition.model_validate(flow_data)
        orch = FlowOrchestrator(flow, tmp_path)
        orch._build_members()

        # Verify load_role was called (not load_and_build) because shared_documents is enabled
        mock_load_role.assert_called_once()
        mock_build_agent.assert_called_once()

        # Verify role was patched with shared document config
        assert role.spec.ingest is not None
        assert role.spec.ingest.store_path == "/tmp/shared.lance"
        assert role.spec.ingest.embeddings.provider == "openai"

    @patch("initrunner.flow.orchestrator.load_and_build")
    def test_unchanged_fast_path(self, mock_load_and_build, tmp_path):
        """When neither shared feature is enabled, load_and_build is called directly."""
        role = _make_role()
        agent = MagicMock()
        mock_load_and_build.return_value = (role, agent)

        roles_dir = tmp_path / "roles"
        roles_dir.mkdir()
        (roles_dir / "a.yaml").write_text("")

        flow_data = {
            "apiVersion": "initrunner/v1",
            "kind": "Flow",
            "metadata": {"name": "test-flow"},
            "spec": {
                "agents": {
                    "a": {"role": "roles/a.yaml"},
                },
            },
        }

        from initrunner.flow.orchestrator import FlowOrchestrator

        flow = FlowDefinition.model_validate(flow_data)
        orch = FlowOrchestrator(flow, tmp_path)
        orch._build_members()

        mock_load_and_build.assert_called_once()
