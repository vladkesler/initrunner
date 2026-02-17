"""Tests for agent/memory_capture.py: episodic auto-capture."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from initrunner.agent.memory_capture import capture_episode
from initrunner.agent.schema import (
    AgentSpec,
    ApiVersion,
    EpisodicMemoryConfig,
    Kind,
    MemoryConfig,
    Metadata,
    ModelConfig,
    RoleDefinition,
)
from initrunner.stores.base import MemoryType


def _make_role(*, episodic_enabled: bool = True) -> RoleDefinition:
    return RoleDefinition(
        apiVersion=ApiVersion.V1,
        kind=Kind.AGENT,
        metadata=Metadata(name="test-agent"),
        spec=AgentSpec(
            role="You are a test.",
            model=ModelConfig(provider="openai", name="gpt-4o-mini"),
            memory=MemoryConfig(
                episodic=EpisodicMemoryConfig(enabled=episodic_enabled),
            ),
        ),
    )


class TestCaptureEpisode:
    @patch("initrunner.ingestion.embeddings.embed_single")
    def test_captures_episode(self, mock_embed):
        mock_embed.return_value = [1.0, 0.0, 0.0, 0.0]
        mock_store = MagicMock()
        mock_store.add_memory.return_value = 1

        role = _make_role()
        capture_episode(mock_store, role, "Task completed successfully", category="test_run")

        mock_store.add_memory.assert_called_once()
        call_kwargs = mock_store.add_memory.call_args
        assert call_kwargs[1]["memory_type"] == MemoryType.EPISODIC
        assert call_kwargs[0][0] == "Task completed successfully"
        assert call_kwargs[0][1] == "test_run"

    @patch("initrunner.ingestion.embeddings.embed_single")
    def test_respects_episodic_disabled(self, mock_embed):
        mock_store = MagicMock()
        role = _make_role(episodic_enabled=False)

        capture_episode(mock_store, role, "Should not be stored")

        mock_store.add_memory.assert_not_called()
        mock_embed.assert_not_called()

    @patch("initrunner.ingestion.embeddings.embed_single")
    def test_never_raises_on_failure(self, mock_embed):
        mock_embed.side_effect = RuntimeError("embed failure")
        mock_store = MagicMock()
        role = _make_role()

        # Should not raise
        capture_episode(mock_store, role, "Test")

    def test_no_memory_config(self):
        role = RoleDefinition(
            apiVersion=ApiVersion.V1,
            kind=Kind.AGENT,
            metadata=Metadata(name="test-agent"),
            spec=AgentSpec(
                role="You are a test.",
                model=ModelConfig(provider="openai", name="gpt-4o-mini"),
            ),
        )
        mock_store = MagicMock()
        capture_episode(mock_store, role, "Test")
        mock_store.add_memory.assert_not_called()

    @patch("initrunner.ingestion.embeddings.embed_single")
    def test_includes_trigger_type_in_metadata(self, mock_embed):
        mock_embed.return_value = [1.0, 0.0, 0.0, 0.0]
        mock_store = MagicMock()
        mock_store.add_memory.return_value = 1

        role = _make_role()
        capture_episode(
            mock_store,
            role,
            "Trigger fired",
            trigger_type="cron",
            metadata={"task": "backup"},
        )

        call_kwargs = mock_store.add_memory.call_args[1]
        assert call_kwargs["metadata"]["trigger_type"] == "cron"
        assert call_kwargs["metadata"]["task"] == "backup"

    @patch("initrunner.ingestion.embeddings.embed_single")
    def test_prunes_after_capture(self, mock_embed):
        mock_embed.return_value = [1.0, 0.0, 0.0, 0.0]
        mock_store = MagicMock()
        mock_store.add_memory.return_value = 1

        role = _make_role()
        capture_episode(mock_store, role, "Test prune")

        mock_store.prune_memories.assert_called_once_with(500, memory_type=MemoryType.EPISODIC)
