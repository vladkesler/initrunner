"""Tests for agent/memory_consolidation.py: consolidation logic."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from initrunner.agent.memory_consolidation import maybe_consolidate
from initrunner.agent.schema.base import ApiVersion, Kind, Metadata, ModelConfig
from initrunner.agent.schema.memory import ConsolidationConfig, MemoryConfig
from initrunner.agent.schema.role import AgentSpec, RoleDefinition
from initrunner.stores.base import Memory, MemoryType


def _make_role(*, consolidation_enabled: bool = True) -> RoleDefinition:
    return RoleDefinition(
        apiVersion=ApiVersion.V1,
        kind=Kind.AGENT,
        metadata=Metadata(name="test-agent"),
        spec=AgentSpec(
            role="You are a test.",
            model=ModelConfig(provider="openai", name="gpt-4o-mini"),
            memory=MemoryConfig(
                consolidation=ConsolidationConfig(enabled=consolidation_enabled),
            ),
        ),
    )


def _make_episode(id: int, content: str, category: str = "test") -> Memory:
    return Memory(
        id=id,
        content=content,
        category=category,
        created_at="2026-01-01T00:00:00+00:00",
        memory_type=MemoryType.EPISODIC,
    )


class TestMaybeConsolidate:
    @patch("initrunner.ingestion.embeddings.embed_single")
    @patch("pydantic_ai.Agent")
    def test_consolidates_episodes(self, mock_agent_cls, mock_embed):
        mock_embed.return_value = [1.0, 0.0, 0.0, 0.0]

        mock_result = MagicMock()
        mock_result.output = "fact: The user prefers dark mode\npattern: Errors happen on Mondays"
        mock_agent = MagicMock()
        mock_agent.run_sync.return_value = mock_result
        mock_agent_cls.return_value = mock_agent

        episodes = [
            _make_episode(1, "User asked for dark mode"),
            _make_episode(2, "Error on Monday"),
        ]

        mock_store = MagicMock()
        mock_store.get_unconsolidated_episodes.return_value = episodes

        role = _make_role()
        created = maybe_consolidate(mock_store, role)

        assert created == 2
        assert mock_store.add_memory.call_count == 2
        mock_store.mark_consolidated.assert_called_once()
        consolidated_ids = mock_store.mark_consolidated.call_args[0][0]
        assert set(consolidated_ids) == {1, 2}

    def test_respects_disabled(self):
        mock_store = MagicMock()
        role = _make_role(consolidation_enabled=False)

        created = maybe_consolidate(mock_store, role)

        assert created == 0
        mock_store.get_unconsolidated_episodes.assert_not_called()

    def test_no_episodes(self):
        mock_store = MagicMock()
        mock_store.get_unconsolidated_episodes.return_value = []

        role = _make_role()
        created = maybe_consolidate(mock_store, role)

        assert created == 0
        mock_store.add_memory.assert_not_called()

    @patch("pydantic_ai.Agent")
    def test_never_raises_on_failure(self, mock_agent_cls):
        mock_agent_cls.side_effect = RuntimeError("LLM failed")

        episodes = [_make_episode(1, "Test")]
        mock_store = MagicMock()
        mock_store.get_unconsolidated_episodes.return_value = episodes

        role = _make_role()
        created = maybe_consolidate(mock_store, role)

        assert created == 0
        mock_store.mark_consolidated.assert_not_called()

    @patch("initrunner.ingestion.embeddings.embed_single")
    @patch("pydantic_ai.Agent")
    def test_zero_results_no_mark(self, mock_agent_cls, mock_embed):
        """LLM returns unparseable output → no episodes marked."""
        mock_result = MagicMock()
        mock_result.output = "I don't have any insights to extract."
        mock_agent = MagicMock()
        mock_agent.run_sync.return_value = mock_result
        mock_agent_cls.return_value = mock_agent

        episodes = [_make_episode(1, "Boring episode")]
        mock_store = MagicMock()
        mock_store.get_unconsolidated_episodes.return_value = episodes

        role = _make_role()
        created = maybe_consolidate(mock_store, role)

        assert created == 0
        mock_store.add_memory.assert_not_called()
        mock_store.mark_consolidated.assert_not_called()

    @patch("initrunner.ingestion.embeddings.embed_single")
    @patch("pydantic_ai.Agent")
    def test_partial_failure_no_mark(self, mock_agent_cls, mock_embed):
        """Store fails during add_memory → no episodes marked as consolidated."""
        mock_embed.return_value = [1.0, 0.0, 0.0, 0.0]

        mock_result = MagicMock()
        mock_result.output = "fact: something"
        mock_agent = MagicMock()
        mock_agent.run_sync.return_value = mock_result
        mock_agent_cls.return_value = mock_agent

        mock_store = MagicMock()
        mock_store.get_unconsolidated_episodes.return_value = [_make_episode(1, "Test")]
        mock_store.add_memory.side_effect = RuntimeError("disk full")

        role = _make_role()
        created = maybe_consolidate(mock_store, role)

        # Should return 0 since the function caught the error
        assert created == 0
        mock_store.mark_consolidated.assert_not_called()

    @patch("initrunner.ingestion.embeddings.embed_single")
    @patch("pydantic_ai.Agent")
    def test_force_overrides_disabled(self, mock_agent_cls, mock_embed):
        mock_embed.return_value = [1.0, 0.0, 0.0, 0.0]

        mock_result = MagicMock()
        mock_result.output = "fact: forced insight"
        mock_agent = MagicMock()
        mock_agent.run_sync.return_value = mock_result
        mock_agent_cls.return_value = mock_agent

        mock_store = MagicMock()
        mock_store.get_unconsolidated_episodes.return_value = [_make_episode(1, "Test")]

        role = _make_role(consolidation_enabled=False)
        created = maybe_consolidate(mock_store, role, force=True)

        assert created == 1
        mock_store.mark_consolidated.assert_called_once()

    @patch("initrunner.ingestion.embeddings.embed_single")
    @patch("pydantic_ai.Agent")
    def test_stores_with_correct_memory_type(self, mock_agent_cls, mock_embed):
        mock_embed.return_value = [1.0, 0.0, 0.0, 0.0]

        mock_result = MagicMock()
        mock_result.output = "fact: extracted fact"
        mock_agent = MagicMock()
        mock_agent.run_sync.return_value = mock_result
        mock_agent_cls.return_value = mock_agent

        mock_store = MagicMock()
        mock_store.get_unconsolidated_episodes.return_value = [_make_episode(1, "Episode")]

        role = _make_role()
        maybe_consolidate(mock_store, role)

        call_kwargs = mock_store.add_memory.call_args[1]
        assert call_kwargs["memory_type"] == MemoryType.SEMANTIC
        assert call_kwargs["metadata"] == {"source": "consolidation"}
