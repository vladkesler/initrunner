"""Tests for agent/memory_ops.py: save_session and finalize_turn return values."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, UserPromptPart

from initrunner.agent.memory_ops import (
    TurnResult,
    build_memory_system_prompt,
    export_memories,
    finalize_turn,
    save_session,
)
from initrunner.agent.schema import (
    AgentSpec,
    ApiVersion,
    Kind,
    MemoryConfig,
    Metadata,
    ModelConfig,
    ProceduralMemoryConfig,
    RoleDefinition,
)
from initrunner.stores.base import Memory, MemoryType


def _make_role(*, memory: MemoryConfig | None = None) -> RoleDefinition:
    return RoleDefinition(
        apiVersion=ApiVersion.V1,
        kind=Kind.AGENT,
        metadata=Metadata(name="test-agent"),
        spec=AgentSpec(
            role="You are a test.",
            model=ModelConfig(provider="openai", name="gpt-4o-mini"),
            memory=memory,
        ),
    )


def _make_messages() -> list:
    return [
        ModelRequest(parts=[UserPromptPart(content="hello")]),
        ModelResponse(parts=[TextPart(content="hi")]),
    ]


class TestSaveSession:
    def test_returns_true_on_success(self):
        mock_store = MagicMock()
        role = _make_role(memory=MemoryConfig())
        with patch("initrunner.stores.factory.open_memory_store") as mock_open:
            mock_open.return_value.__enter__ = MagicMock(return_value=mock_store)
            mock_open.return_value.__exit__ = MagicMock(return_value=False)
            result = save_session(role, "session-1", _make_messages())
        assert result is True

    def test_returns_false_when_store_raises(self):
        mock_store = MagicMock()
        mock_store.save_session.side_effect = RuntimeError("disk full")
        role = _make_role(memory=MemoryConfig())
        with patch("initrunner.stores.factory.open_memory_store") as mock_open:
            mock_open.return_value.__enter__ = MagicMock(return_value=mock_store)
            mock_open.return_value.__exit__ = MagicMock(return_value=False)
            result = save_session(role, "session-1", _make_messages())
        assert result is False

    def test_returns_true_when_no_store(self):
        role = _make_role(memory=MemoryConfig())
        with patch("initrunner.stores.factory.open_memory_store") as mock_open:
            mock_open.return_value.__enter__ = MagicMock(return_value=None)
            mock_open.return_value.__exit__ = MagicMock(return_value=False)
            result = save_session(role, "session-1", _make_messages())
        assert result is True


class TestFinalizeTurn:
    @patch("initrunner.agent.history.trim_message_history", side_effect=lambda m, _: m)
    @patch("initrunner.agent.history.session_limits", return_value=(20, 40))
    def test_returns_turn_result_success(self, _mock_limits, _mock_trim):
        mock_store = MagicMock()
        role = _make_role(memory=MemoryConfig())
        msgs = _make_messages()
        result = finalize_turn(role, "session-1", msgs, memory_store=mock_store)
        assert isinstance(result, TurnResult)
        assert result.save_ok is True
        assert result.messages == msgs

    @patch("initrunner.agent.history.trim_message_history", side_effect=lambda m, _: m)
    @patch("initrunner.agent.history.session_limits", return_value=(20, 40))
    def test_returns_save_ok_false_when_store_raises(self, _mock_limits, _mock_trim):
        mock_store = MagicMock()
        mock_store.save_session.side_effect = RuntimeError("disk full")
        role = _make_role(memory=MemoryConfig())
        msgs = _make_messages()
        result = finalize_turn(role, "session-1", msgs, memory_store=mock_store)
        assert isinstance(result, TurnResult)
        assert result.save_ok is False
        assert result.messages == msgs

    @patch("initrunner.agent.history.trim_message_history", side_effect=lambda m, _: m)
    @patch("initrunner.agent.history.session_limits", return_value=(20, 40))
    def test_returns_save_ok_true_when_no_store(self, _mock_limits, _mock_trim):
        role = _make_role(memory=MemoryConfig())
        msgs = _make_messages()
        result = finalize_turn(role, "session-1", msgs, memory_store=None)
        assert isinstance(result, TurnResult)
        assert result.save_ok is True


class TestBuildMemorySystemPrompt:
    def test_loads_procedural_memories(self):
        proc_memories = [
            Memory(
                id=1,
                content="Always greet the user",
                category="policy",
                created_at="2026-01-01T00:00:00",
                memory_type=MemoryType.PROCEDURAL,
            ),
            Memory(
                id=2,
                content="Use JSON for API responses",
                category="format",
                created_at="2026-01-01T00:00:00",
                memory_type=MemoryType.PROCEDURAL,
            ),
        ]
        mock_store = MagicMock()
        mock_store.list_memories.return_value = proc_memories

        role = _make_role(memory=MemoryConfig())

        with patch("initrunner.stores.factory.open_memory_store") as mock_open:
            mock_open.return_value.__enter__ = MagicMock(return_value=mock_store)
            mock_open.return_value.__exit__ = MagicMock(return_value=False)
            result = build_memory_system_prompt(role)

        assert "Learned Procedures and Policies" in result
        assert "Always greet the user" in result
        assert "Use JSON for API responses" in result

    def test_returns_empty_when_no_memory(self):
        role = _make_role()
        result = build_memory_system_prompt(role)
        assert result == ""

    def test_returns_empty_when_procedural_disabled(self):
        role = _make_role(memory=MemoryConfig(procedural=ProceduralMemoryConfig(enabled=False)))
        result = build_memory_system_prompt(role)
        assert result == ""

    def test_returns_empty_on_failure(self):
        role = _make_role(memory=MemoryConfig())
        with patch("initrunner.stores.factory.open_memory_store") as mock_open:
            mock_open.side_effect = RuntimeError("db error")
            result = build_memory_system_prompt(role)
        assert result == ""

    def test_returns_empty_when_no_procedures(self):
        mock_store = MagicMock()
        mock_store.list_memories.return_value = []

        role = _make_role(memory=MemoryConfig())

        with patch("initrunner.stores.factory.open_memory_store") as mock_open:
            mock_open.return_value.__enter__ = MagicMock(return_value=mock_store)
            mock_open.return_value.__exit__ = MagicMock(return_value=False)
            result = build_memory_system_prompt(role)

        assert result == ""


class TestExportMemoriesWithTypes:
    def test_export_includes_memory_type(self):
        mock_store = MagicMock()
        mock_store.list_memories.return_value = [
            Memory(
                id=1,
                content="fact",
                category="general",
                created_at="2026-01-01",
                memory_type=MemoryType.SEMANTIC,
            ),
            Memory(
                id=2,
                content="episode",
                category="run",
                created_at="2026-01-01",
                memory_type=MemoryType.EPISODIC,
                metadata={"tool_calls": 3},
            ),
        ]

        role = _make_role(memory=MemoryConfig())

        with patch("initrunner.stores.factory.open_memory_store") as mock_open:
            mock_open.return_value.__enter__ = MagicMock(return_value=mock_store)
            mock_open.return_value.__exit__ = MagicMock(return_value=False)
            result = export_memories(role)

        assert len(result) == 2
        assert result[0]["memory_type"] == "semantic"
        assert result[1]["memory_type"] == "episodic"
        assert result[1]["metadata"] == {"tool_calls": 3}
