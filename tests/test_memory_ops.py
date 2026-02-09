"""Tests for agent/memory_ops.py: save_session and finalize_turn return values."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, UserPromptPart

from initrunner.agent.memory_ops import TurnResult, finalize_turn, save_session
from initrunner.agent.schema import (
    AgentSpec,
    ApiVersion,
    Kind,
    MemoryConfig,
    Metadata,
    ModelConfig,
    RoleDefinition,
)


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
