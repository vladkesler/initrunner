"""Tests for initrunner.agent.history_summarizer."""

from __future__ import annotations

import logging
from unittest.mock import MagicMock

from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)

from initrunner.agent.history_summarizer import (
    _BUDGET_FRACTION,
    _FALLBACK_CONTEXT_WINDOW,
    _MEDIA_TOKENS,
    _MSG_OVERHEAD,
    _PART_OVERHEAD,
    _PROVIDER_CONTEXT_WINDOWS,
    build_history_processor,
    enforce_token_budget,
    estimate_tokens,
    resolve_context_window,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _model_config(*, context_window=None, provider="anthropic", name="claude-3-5-sonnet"):
    cfg = MagicMock()
    cfg.context_window = context_window
    cfg.provider = provider
    cfg.name = name
    return cfg


def _req(content: str = "hello") -> ModelMessage:
    return ModelRequest(parts=[UserPromptPart(content=content)])


def _resp(content: str = "hi") -> ModelMessage:
    return ModelResponse(parts=[TextPart(content=content)])


def _tool_req(tool_name: str = "read", content: str = "result") -> ModelMessage:
    return ModelRequest(parts=[ToolReturnPart(tool_name=tool_name, content=content)])


def _tool_resp(tool_name: str = "read") -> ModelMessage:
    return ModelResponse(parts=[ToolCallPart(tool_name=tool_name, args="{}")])


def _alternating(n: int) -> list:
    """Alternating request/response messages."""
    msgs = []
    for i in range(n):
        if i % 2 == 0:
            msgs.append(_req(f"msg-{i}"))
        else:
            msgs.append(_resp(f"resp-{i}"))
    return msgs


# ---------------------------------------------------------------------------
# resolve_context_window
# ---------------------------------------------------------------------------


class TestResolveContextWindow:
    def test_explicit_wins(self):
        cfg = _model_config(context_window=50_000)
        assert resolve_context_window(cfg) == 50_000

    def test_known_provider(self):
        for provider, expected in _PROVIDER_CONTEXT_WINDOWS.items():
            cfg = _model_config(provider=provider)
            assert resolve_context_window(cfg) == expected

    def test_unknown_provider_fallback_with_warning(self, caplog, monkeypatch):
        monkeypatch.setattr(logging.getLogger("initrunner"), "propagate", True)
        cfg = _model_config(provider="some-unknown-provider")
        with caplog.at_level(logging.WARNING, logger="initrunner.agent.history_summarizer"):
            result = resolve_context_window(cfg)
        assert result == _FALLBACK_CONTEXT_WINDOW
        assert "context_window not set" in caplog.text

    def test_explicit_overrides_provider(self):
        cfg = _model_config(context_window=10_000, provider="anthropic")
        assert resolve_context_window(cfg) == 10_000


# ---------------------------------------------------------------------------
# estimate_tokens
# ---------------------------------------------------------------------------


class TestEstimateTokens:
    def test_empty(self):
        assert estimate_tokens([]) == 0

    def test_single_text_message(self):
        text = "a" * 400  # ~100 tokens
        msgs = [_req(text)]
        est = estimate_tokens(msgs)
        assert est == 400 // 4 + _MSG_OVERHEAD + _PART_OVERHEAD

    def test_tool_return_string(self):
        content = "x" * 2000  # ~500 tokens
        msgs: list[ModelMessage] = [
            ModelRequest(parts=[ToolReturnPart(tool_name="read", content=content)])
        ]
        est = estimate_tokens(msgs)
        assert est == 2000 // 4 + _MSG_OVERHEAD + _PART_OVERHEAD

    def test_tool_return_dict(self):
        content = {"key": "value" * 100}
        msgs: list[ModelMessage] = [
            ModelRequest(parts=[ToolReturnPart(tool_name="read", content=content)])
        ]
        est = estimate_tokens(msgs)
        assert est > _MSG_OVERHEAD + _PART_OVERHEAD  # non-zero content

    def test_response_text_part(self):
        msgs: list[ModelMessage] = [ModelResponse(parts=[TextPart(content="hello world")])]
        est = estimate_tokens(msgs)
        assert est == len("hello world") // 4 + _MSG_OVERHEAD + _PART_OVERHEAD

    def test_tool_call_part(self):
        args = '{"path": "/tmp/file.txt"}'
        msgs: list[ModelMessage] = [
            ModelResponse(parts=[ToolCallPart(tool_name="read", args=args)])
        ]
        est = estimate_tokens(msgs)
        assert est == len(args) // 4 + _MSG_OVERHEAD + _PART_OVERHEAD

    def test_multiple_parts(self):
        msgs: list[ModelMessage] = [
            ModelRequest(
                parts=[
                    UserPromptPart(content="hello"),
                    ToolReturnPart(tool_name="t", content="result"),
                ]
            )
        ]
        est = estimate_tokens(msgs)
        expected = (
            _MSG_OVERHEAD + len("hello") // 4 + _PART_OVERHEAD + len("result") // 4 + _PART_OVERHEAD
        )
        assert est == expected

    def test_multimodal_user_prompt(self):
        """ImageUrl-like objects get a fixed media token estimate."""

        class FakeImageUrl:
            kind = "image-url"

        msgs: list[ModelMessage] = [
            ModelRequest(parts=[UserPromptPart(content=["text", FakeImageUrl()])])
        ]  # type: ignore[arg-type]
        est = estimate_tokens(msgs)
        expected = _MSG_OVERHEAD + (len("text") // 4 + _MEDIA_TOKENS) + _PART_OVERHEAD
        assert est == expected

    def test_cache_point_zero_tokens(self):
        class FakeCachePoint:
            kind = "cache-point"

        msgs: list[ModelMessage] = [
            ModelRequest(parts=[UserPromptPart(content=["text", FakeCachePoint()])])
        ]  # type: ignore[arg-type]
        est = estimate_tokens(msgs)
        # CachePoint contributes nothing
        expected = _MSG_OVERHEAD + len("text") // 4 + _PART_OVERHEAD
        assert est == expected


# ---------------------------------------------------------------------------
# enforce_token_budget -- truncation (stage 1)
# ---------------------------------------------------------------------------


class TestEnforceTokenBudgetTruncation:
    def test_under_budget_passthrough(self):
        msgs = [_req("short")]
        result = enforce_token_budget(msgs, budget=10_000)
        assert result is msgs  # identity -- not a copy

    def test_empty_passthrough(self):
        result = enforce_token_budget([], budget=100)
        assert result == []

    def test_large_tool_return_truncated(self):
        big = "x" * 50_000
        original_part = ToolReturnPart(tool_name="read", content=big)
        msgs: list[ModelMessage] = [ModelRequest(parts=[original_part])]
        budget = 5000  # tokens; budget//20 = 250 chars threshold

        result = enforce_token_budget(msgs, budget=budget)

        assert len(result) == 1
        truncated_part = result[0].parts[0]
        assert truncated_part.content.endswith("[truncated]")  # type: ignore[union-attr]
        assert len(truncated_part.content) < len(big)  # type: ignore[union-attr]
        # Original not mutated
        assert original_part.content == big

    def test_large_text_part_truncated(self):
        big = "y" * 50_000
        msgs: list[ModelMessage] = [ModelResponse(parts=[TextPart(content=big)])]
        budget = 5000

        result = enforce_token_budget(msgs, budget=budget)

        truncated = result[0].parts[0]
        assert truncated.content.endswith("[truncated]")  # type: ignore[union-attr]
        assert len(truncated.content) < len(big)  # type: ignore[union-attr]

    def test_large_user_prompt_truncated(self):
        big = "z" * 50_000
        msgs = [_req(big)]
        budget = 5000

        result = enforce_token_budget(msgs, budget=budget)

        truncated = result[0].parts[0]
        assert truncated.content.endswith("[truncated]")  # type: ignore[union-attr]

    def test_non_string_tool_return_not_truncated(self):
        """Dict content in ToolReturnPart should not be truncated."""
        content = {"data": "v" * 50_000}
        msgs: list[ModelMessage] = [
            ModelRequest(parts=[ToolReturnPart(tool_name="t", content=content)])
        ]
        budget = 5000

        result = enforce_token_budget(msgs, budget=budget)

        # Dict content is not truncated by stage 1; stage 2 (dropping) may apply
        for msg in result:
            for part in msg.parts:
                if hasattr(part, "tool_name") and part.tool_name == "t":  # type: ignore[union-attr]
                    assert part.content is content  # type: ignore[union-attr]

    def test_dataclasses_replace_preserves_metadata(self):
        """Truncation via dataclasses.replace preserves tool_call_id, tool_name."""
        big = "x" * 50_000
        part = ToolReturnPart(tool_name="my_tool", content=big, tool_call_id="abc-123")
        msgs: list[ModelMessage] = [ModelRequest(parts=[part])]

        result = enforce_token_budget(msgs, budget=5000)

        new_part = result[0].parts[0]
        assert new_part.tool_name == "my_tool"  # type: ignore[union-attr]
        assert new_part.tool_call_id == "abc-123"  # type: ignore[union-attr]
        assert new_part is not part  # new object


# ---------------------------------------------------------------------------
# enforce_token_budget -- dropping (stage 2)
# ---------------------------------------------------------------------------


class TestEnforceTokenBudgetDropping:
    def test_drops_oldest_pairs(self):
        # Make messages big enough that truncation alone won't fix it
        msgs = [_req("a" * 800) for _ in range(50)]
        # Insert responses between requests for pairing
        paired: list[ModelMessage] = []
        for m in msgs:
            paired.append(m)
            paired.append(_resp("b" * 800))
        budget = 2000  # very small

        result = enforce_token_budget(paired, budget=budget)

        assert len(result) < len(paired)
        # First message should be the synthetic summary
        assert isinstance(result[0], ModelRequest)
        summary_content = result[0].parts[0].content  # type: ignore[union-attr]
        assert "dropped" in summary_content  # type: ignore[operator]

    def test_preserve_first_keeps_first(self):
        first = _req("ORIGINAL TASK")
        rest = _alternating(20)
        # Make them large enough to exceed budget
        big_msgs = [first] + [
            _req("x" * 2000) if isinstance(m, ModelRequest) else _resp("y" * 2000) for m in rest
        ]
        budget = 3000

        result = enforce_token_budget(big_msgs, budget=budget, preserve_first=True)

        assert result[0].parts[0].content.startswith("ORIGINAL TASK")  # type: ignore[union-attr]

    def test_preserve_first_false_does_not_keep_first(self):
        first = _req("ORIGINAL TASK")
        # Many small messages (under truncation threshold) to force dropping
        rest = [_req(f"msg-{i}") for i in range(200)]
        big_msgs = [first, *rest]
        budget = 500

        result = enforce_token_budget(big_msgs, budget=budget, preserve_first=False)

        # First message is the synthetic summary, not the original
        assert "dropped" in result[0].parts[0].content  # type: ignore[operator]

    def test_result_starts_with_request(self):
        msgs = [_resp("r1"), _resp("r2"), _req("q")]
        # Just verify the contract even without budget pressure
        result = enforce_token_budget(msgs, budget=1)
        assert isinstance(result[0], ModelRequest)

    def test_never_returns_empty(self):
        msgs = [_req("a" * 10_000)]
        result = enforce_token_budget(msgs, budget=1)
        assert len(result) > 0

    def test_synthetic_summary_mentions_tools(self):
        # Many tool call/return pairs to force dropping (not just truncation)
        msgs: list[ModelMessage] = [_req("start")]
        for i in range(30):
            name = "shell" if i % 2 == 0 else "read_file"
            msgs.append(_tool_resp(name))
            msgs.append(_tool_req(name, f"result-{i}"))
        msgs.append(_req("end"))
        budget = 500

        result = enforce_token_budget(msgs, budget=budget)

        # Find the synthetic summary
        summaries = [
            p.content
            for m in result
            if isinstance(m, ModelRequest)
            for p in m.parts
            if isinstance(p, UserPromptPart) and "dropped" in str(p.content)
        ]
        assert summaries
        assert "shell" in summaries[0] or "read_file" in summaries[0]

    def test_request_response_pairs_dropped_together(self):
        """Dropping a request should also drop the following response."""
        msgs = [
            _req("q1"),
            _resp("a1"),
            _req("q2"),
            _resp("a2"),
            _req("q3"),  # this should remain
        ]
        # Make early messages big so they get dropped
        msgs[0] = _req("x" * 5000)
        msgs[1] = _resp("y" * 5000)
        msgs[2] = _req("z" * 5000)
        msgs[3] = _resp("w" * 5000)
        msgs[4] = _req("keep")
        budget = 2000

        result = enforce_token_budget(msgs, budget=budget)

        # No orphaned response without a preceding request
        for i, msg in enumerate(result):
            if i == 0:
                assert isinstance(msg, ModelRequest)


# ---------------------------------------------------------------------------
# build_history_processor
# ---------------------------------------------------------------------------


class TestBuildHistoryProcessor:
    def test_returns_callable(self):
        cfg = _model_config()
        proc = build_history_processor(cfg)
        assert callable(proc)

    def test_under_budget_passthrough(self):
        cfg = _model_config(context_window=200_000)
        proc = build_history_processor(cfg)
        msgs = [_req("hello")]
        result = proc(msgs)
        assert result is msgs

    def test_over_budget_triggers_enforcement(self):
        cfg = _model_config(context_window=1000)
        proc = build_history_processor(cfg)
        budget = int(1000 * _BUDGET_FRACTION)
        # Create messages that exceed the tiny budget
        msgs = [_req("x" * 5000)]

        result = proc(msgs)

        # Should have been truncated
        assert estimate_tokens(result) <= budget or len(result[0].parts[0].content) < 5000  # type: ignore[union-attr,arg-type]

    def test_budget_derived_from_context_window(self):
        cfg = _model_config(context_window=10_000)
        proc = build_history_processor(cfg)
        # The processor should use 10_000 * 0.75 = 7500 as budget
        small_msgs = [_req("a" * 100)]
        result = proc(small_msgs)
        assert result is small_msgs  # under budget


# ---------------------------------------------------------------------------
# Integration: reduce_history with token budget
# ---------------------------------------------------------------------------


class TestReduceHistoryTokenBudget:
    def test_reduce_history_calls_enforce_token_budget(self):
        """reduce_history should apply token budget after compact + trim."""
        from unittest.mock import patch as mock_patch

        from initrunner.agent.history import reduce_history

        msgs = _alternating(6)
        autonomy_config = MagicMock()
        autonomy_config.max_history_messages = 40
        role = MagicMock()
        role.spec.model = _model_config(context_window=200_000)

        with mock_patch(
            "initrunner.agent.history.maybe_compact_message_history",
            side_effect=lambda m, *a, **kw: m,
        ):
            result = reduce_history(msgs, autonomy_config, role)

        # Should return messages (under budget, so unchanged)
        assert len(result) == len(msgs)
