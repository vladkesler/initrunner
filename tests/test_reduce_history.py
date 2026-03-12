"""Tests for initrunner.agent.history.reduce_history."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, UserPromptPart

from initrunner.agent.history import reduce_history

_COMPACT = "initrunner.agent.history.maybe_compact_message_history"


def _make_messages(n: int):
    """Return alternating request/response messages."""
    msgs = []
    for i in range(n):
        if i % 2 == 0:
            msgs.append(ModelRequest(parts=[UserPromptPart(content=f"msg-{i}")]))
        else:
            msgs.append(ModelResponse(parts=[TextPart(content=f"resp-{i}")]))
    return msgs


def _make_autonomy_config(max_history_messages: int = 10, **kwargs):
    cfg = MagicMock()
    cfg.max_history_messages = max_history_messages
    for k, v in kwargs.items():
        setattr(cfg, k, v)
    return cfg


def _passthrough(m, *a, **kw):
    return m


class TestReduceHistory:
    @patch(_COMPACT, side_effect=_passthrough)
    def test_preserve_first_true(self, _mock_compact):
        """preserve_first=True keeps the first message."""
        msgs = _make_messages(20)
        role = MagicMock()
        cfg = _make_autonomy_config(max_history_messages=6)

        result = reduce_history(msgs, cfg, role, preserve_first=True)

        assert result[0] is msgs[0]
        assert len(result) <= 6
        _mock_compact.assert_called_once_with(msgs, cfg, role, preserve_first=True)

    @patch(_COMPACT, side_effect=_passthrough)
    def test_preserve_first_false(self, _mock_compact):
        """Default (preserve_first=False) trims from the end only."""
        msgs = _make_messages(20)
        role = MagicMock()
        cfg = _make_autonomy_config(max_history_messages=6)

        result = reduce_history(msgs, cfg, role)

        assert len(result) <= 6
        _mock_compact.assert_called_once_with(msgs, cfg, role, preserve_first=False)

    @patch(_COMPACT, side_effect=_passthrough)
    def test_short_history_unchanged(self, _mock_compact):
        """Messages within budget are returned as-is."""
        msgs = _make_messages(4)
        role = MagicMock()
        cfg = _make_autonomy_config(max_history_messages=10)

        result = reduce_history(msgs, cfg, role)

        assert result == msgs
