"""Tests for memory import functionality."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from initrunner.agent.memory_ops import import_memories
from initrunner.agent.schema.base import ApiVersion, Kind, ModelConfig, RoleMetadata
from initrunner.agent.schema.memory import MemoryConfig
from initrunner.agent.schema.role import AgentSpec, RoleDefinition
from initrunner.stores.base import MemoryType

_EMBED_MOD = "initrunner.ingestion.embeddings"
_FACTORY_MOD = "initrunner.stores.factory"


def _make_role(*, memory: MemoryConfig | None = None) -> RoleDefinition:
    return RoleDefinition(
        apiVersion=ApiVersion.V1,
        kind=Kind.AGENT,
        metadata=RoleMetadata(name="test-agent"),
        spec=AgentSpec(
            role="You are a test.",
            model=ModelConfig(provider="openai", name="gpt-5-mini"),
            memory=memory,
        ),
    )


def _make_async_embed(return_values):
    """Create a fake embed_texts that returns a coroutine with given values.

    If *return_values* is a list of lists, pops from the front on each call
    (for multi-batch scenarios).
    """
    call_count = [0]
    call_args = []

    async def _embed(embedder, texts, *, input_type="document"):
        idx = call_count[0]
        call_count[0] += 1
        call_args.append((embedder, texts))
        if (
            isinstance(return_values, list)
            and return_values
            and isinstance(return_values[0], list)
            and isinstance(return_values[0][0], list)
        ):
            # Multi-batch: return_values is list of batches
            return return_values[idx]
        return return_values

    _embed._call_args = call_args  # type: ignore[attr-defined]
    _embed._call_count = call_count  # type: ignore[attr-defined]
    return _embed


class TestImportMemoriesBasic:
    @patch(f"{_EMBED_MOD}.create_embedder")
    def test_import_memories_basic(self, mock_create):
        mock_create.return_value = MagicMock()
        fake_embed = _make_async_embed([[0.1, 0.2, 0.3, 0.4]] * 3)

        mock_store = MagicMock()
        mock_store.add_memory.return_value = 1
        role = _make_role(memory=MemoryConfig())

        data = [
            {"content": "fact one", "category": "general", "memory_type": "semantic"},
            {"content": "episode one", "category": "run", "memory_type": "episodic"},
            {"content": "procedure one", "category": "policy", "memory_type": "procedural"},
        ]

        with (
            patch(f"{_EMBED_MOD}.embed_texts", fake_embed),
            patch(f"{_FACTORY_MOD}.open_memory_store") as mock_open,
        ):
            mock_open.return_value.__enter__ = MagicMock(return_value=mock_store)
            mock_open.return_value.__exit__ = MagicMock(return_value=False)
            count = import_memories(role, data)

        assert count == 3
        assert mock_store.add_memory.call_count == 3

        # Verify memory types were correctly passed
        calls = mock_store.add_memory.call_args_list
        assert calls[0].kwargs["memory_type"] == MemoryType.SEMANTIC
        assert calls[1].kwargs["memory_type"] == MemoryType.EPISODIC
        assert calls[2].kwargs["memory_type"] == MemoryType.PROCEDURAL

    @patch(f"{_EMBED_MOD}.create_embedder")
    def test_import_memories_preserves_created_at(self, mock_create):
        mock_create.return_value = MagicMock()
        fake_embed = _make_async_embed([[0.1, 0.2, 0.3, 0.4]])

        mock_store = MagicMock()
        mock_store.add_memory.return_value = 1
        role = _make_role(memory=MemoryConfig())

        data = [
            {
                "content": "old fact",
                "category": "general",
                "memory_type": "semantic",
                "created_at": "2025-01-15T10:00:00+00:00",
            },
        ]

        with (
            patch(f"{_EMBED_MOD}.embed_texts", fake_embed),
            patch(f"{_FACTORY_MOD}.open_memory_store") as mock_open,
        ):
            mock_open.return_value.__enter__ = MagicMock(return_value=mock_store)
            mock_open.return_value.__exit__ = MagicMock(return_value=False)
            import_memories(role, data)

        call_kwargs = mock_store.add_memory.call_args_list[0].kwargs
        assert call_kwargs["created_at"] == "2025-01-15T10:00:00+00:00"

    @patch(f"{_EMBED_MOD}.create_embedder")
    def test_import_memories_blank_content_skipped(self, mock_create):
        mock_create.return_value = MagicMock()
        fake_embed = _make_async_embed([[0.1, 0.2, 0.3, 0.4]])

        mock_store = MagicMock()
        mock_store.add_memory.return_value = 1
        role = _make_role(memory=MemoryConfig())

        data = [
            {"content": "", "category": "general"},
            {"content": "real fact", "category": "general"},
            {"category": "general"},  # missing content key
        ]

        with (
            patch(f"{_EMBED_MOD}.embed_texts", fake_embed),
            patch(f"{_FACTORY_MOD}.open_memory_store") as mock_open,
        ):
            mock_open.return_value.__enter__ = MagicMock(return_value=mock_store)
            mock_open.return_value.__exit__ = MagicMock(return_value=False)
            count = import_memories(role, data)

        assert count == 1
        assert mock_store.add_memory.call_count == 1


class TestImportMemoriesValidation:
    @patch(f"{_EMBED_MOD}.create_embedder")
    def test_unknown_type_fails_fast(self, mock_create):
        mock_create.return_value = MagicMock()
        role = _make_role(memory=MemoryConfig())
        data = [
            {"content": "fact", "memory_type": "invalid_type"},
        ]

        with pytest.raises(ValueError, match="Record 0: unknown memory_type 'invalid_type'"):
            import_memories(role, data)

    @patch(f"{_EMBED_MOD}.create_embedder")
    def test_malformed_record_fails_fast(self, mock_create):
        mock_create.return_value = MagicMock()
        role = _make_role(memory=MemoryConfig())
        # Intentionally pass non-dict items to test validation
        data = ["not a dict"]  # type: ignore[list-item]

        with pytest.raises(ValueError, match="Record 0: expected a dict, got str"):
            import_memories(role, data)  # type: ignore[invalid-argument-type]

    def test_no_memory_config_raises(self):
        role = _make_role()  # no memory config
        with pytest.raises(ValueError, match="Role has no memory config"):
            import_memories(role, [{"content": "test"}])

    @patch(f"{_EMBED_MOD}.create_embedder")
    def test_empty_data_returns_zero(self, mock_create):
        mock_create.return_value = MagicMock()
        role = _make_role(memory=MemoryConfig())
        count = import_memories(role, [])
        assert count == 0

    @patch(f"{_EMBED_MOD}.create_embedder")
    def test_all_blank_returns_zero(self, mock_create):
        mock_create.return_value = MagicMock()
        role = _make_role(memory=MemoryConfig())
        count = import_memories(role, [{"content": ""}, {"content": ""}])
        assert count == 0


class TestImportMemoriesBatching:
    @patch(f"{_EMBED_MOD}.create_embedder")
    def test_batch_embedding_calls(self, mock_create):
        mock_create.return_value = MagicMock()
        # 75 entries => 2 batches (50 + 25)
        batch_results = [
            [[0.1] * 4] * 50,
            [[0.2] * 4] * 25,
        ]
        fake_embed = _make_async_embed(batch_results)

        mock_store = MagicMock()
        mock_store.add_memory.return_value = 1
        role = _make_role(memory=MemoryConfig())

        data = [{"content": f"fact {i}", "category": "general"} for i in range(75)]

        with (
            patch(f"{_EMBED_MOD}.embed_texts", fake_embed),
            patch(f"{_FACTORY_MOD}.open_memory_store") as mock_open,
        ):
            mock_open.return_value.__enter__ = MagicMock(return_value=mock_store)
            mock_open.return_value.__exit__ = MagicMock(return_value=False)
            count = import_memories(role, data)

        assert count == 75
        assert fake_embed._call_count[0] == 2
        # First batch: 50 texts
        assert len(fake_embed._call_args[0][1]) == 50
        # Second batch: 25 texts
        assert len(fake_embed._call_args[1][1]) == 25
