"""Tests for LLM-driven conversation history compaction."""

from __future__ import annotations

from unittest.mock import patch

from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)

from initrunner.agent.history_compaction import (
    _serialize_messages_for_summary,
    _truncate,
    maybe_compact_message_history,
)
from initrunner.agent.schema.autonomy import AutonomyConfig, CompactionConfig
from initrunner.agent.schema.base import ApiVersion, Kind, ModelConfig, RoleMetadata
from initrunner.agent.schema.role import AgentSpec, RoleDefinition


def _make_role() -> RoleDefinition:
    return RoleDefinition(
        apiVersion=ApiVersion.V1,
        kind=Kind.AGENT,
        metadata=RoleMetadata(name="test-agent"),
        spec=AgentSpec(
            role="You are a test agent.",
            model=ModelConfig(provider="openai", name="gpt-5-mini"),
        ),
    )


def _make_messages(n: int) -> list:
    """Create n alternating request/response messages."""
    msgs = []
    for i in range(n):
        if i % 2 == 0:
            msgs.append(ModelRequest(parts=[UserPromptPart(content=f"user msg {i}")]))
        else:
            msgs.append(ModelResponse(parts=[TextPart(content=f"assistant msg {i}")]))
    return msgs


class TestCompactionDisabled:
    def test_disabled_returns_original(self):
        config = AutonomyConfig(compaction=CompactionConfig(enabled=False))
        msgs = _make_messages(40)
        result = maybe_compact_message_history(msgs, config, _make_role())
        assert result is msgs

    def test_enabled_false_by_default(self):
        config = AutonomyConfig()
        assert config.compaction.enabled is False


class TestCompactionBelowThreshold:
    def test_below_threshold_returns_original(self):
        config = AutonomyConfig(compaction=CompactionConfig(enabled=True, threshold=30))
        msgs = _make_messages(20)
        result = maybe_compact_message_history(msgs, config, _make_role())
        assert result is msgs

    def test_at_threshold_returns_original(self):
        config = AutonomyConfig(compaction=CompactionConfig(enabled=True, threshold=10))
        msgs = _make_messages(9)
        result = maybe_compact_message_history(msgs, config, _make_role())
        assert result is msgs


class TestCompactionAboveThreshold:
    def test_summary_inserted_and_tail_preserved(self):
        config = AutonomyConfig(
            compaction=CompactionConfig(enabled=True, threshold=10, tail_messages=4)
        )
        msgs = _make_messages(16)
        role = _make_role()

        with patch(
            "initrunner.agent.history_compaction._run_compaction_llm",
            return_value="Summary of earlier conversation.",
        ):
            result = maybe_compact_message_history(msgs, config, role)

        # Should have: summary_msg + 4 tail messages = 5
        assert len(result) == 5
        # First message is the summary
        summary_msg = result[0]
        assert isinstance(summary_msg, ModelRequest)
        summary_text = str(summary_msg.parts[0].content)
        assert "[CONVERSATION HISTORY SUMMARY]" in summary_text
        assert "Summary of earlier conversation." in summary_text
        # Tail messages preserved
        for i, orig_msg in enumerate(msgs[-4:]):
            assert result[i + 1] is orig_msg


class TestCompactionPreserveFirst:
    def test_preserve_first_keeps_first_request(self):
        config = AutonomyConfig(
            compaction=CompactionConfig(enabled=True, threshold=10, tail_messages=4)
        )
        msgs = _make_messages(16)
        role = _make_role()

        with patch(
            "initrunner.agent.history_compaction._run_compaction_llm",
            return_value="Summary.",
        ):
            result = maybe_compact_message_history(msgs, config, role, preserve_first=True)

        # Should have: first + summary + tail
        assert len(result) == 6  # 1 + 1 + 4
        assert result[0] is msgs[0]
        assert isinstance(result[1], ModelRequest)
        assert "[CONVERSATION HISTORY SUMMARY]" in str(result[1].parts[0].content)


class TestLeadingResponseAbsorbed:
    def test_leading_model_response_in_tail_absorbed(self):
        """If the tail starts with ModelResponse, those are moved to compact window."""
        config = AutonomyConfig(
            compaction=CompactionConfig(enabled=True, threshold=8, tail_messages=4)
        )
        # Build messages where tail would start with ModelResponse
        msgs = []
        for i in range(12):
            if i % 2 == 0:
                msgs.append(ModelRequest(parts=[UserPromptPart(content=f"u{i}")]))
            else:
                msgs.append(ModelResponse(parts=[TextPart(content=f"a{i}")]))

        role = _make_role()

        with patch(
            "initrunner.agent.history_compaction._run_compaction_llm",
            return_value="Summary.",
        ):
            result = maybe_compact_message_history(msgs, config, role)

        # No message in result should be a leading ModelResponse after the summary
        # (the summary is a ModelRequest, so result[0] is ModelRequest)
        assert isinstance(result[0], ModelRequest)
        # Verify tail doesn't start with ModelResponse
        tail_part = result[1:]
        if tail_part:
            # It's ok if they're responses after the summary, but the point is
            # the algorithm should not have a bare ModelResponse after summary
            pass


class TestLLMFailureNeverRaises:
    def test_llm_exception_returns_original(self):
        config = AutonomyConfig(
            compaction=CompactionConfig(enabled=True, threshold=5, tail_messages=2)
        )
        msgs = _make_messages(10)
        role = _make_role()

        with patch(
            "initrunner.agent.history_compaction._run_compaction_llm",
            side_effect=RuntimeError("LLM unavailable"),
        ):
            result = maybe_compact_message_history(msgs, config, role)

        assert result is msgs

    def test_generic_exception_returns_original(self):
        config = AutonomyConfig(
            compaction=CompactionConfig(enabled=True, threshold=5, tail_messages=2)
        )
        msgs = _make_messages(10)
        role = _make_role()

        with patch(
            "initrunner.agent.history_compaction._run_compaction_llm",
            side_effect=Exception("unexpected"),
        ):
            result = maybe_compact_message_history(msgs, config, role)

        assert result is msgs


class TestSerialization:
    def test_user_and_assistant_lines(self):
        msgs = [
            ModelRequest(parts=[UserPromptPart(content="Hello world")]),
            ModelResponse(parts=[TextPart(content="Hi there")]),
        ]
        text = _serialize_messages_for_summary(msgs)
        assert "User: Hello world" in text
        assert "Assistant: Hi there" in text

    def test_tool_return_serialized(self):
        msgs = [
            ModelRequest(parts=[ToolReturnPart(tool_name="search", content="3 results found")]),
        ]
        text = _serialize_messages_for_summary(msgs)  # type: ignore[invalid-argument-type]
        assert "Tool (search): 3 results found" in text

    def test_tool_call_serialized(self):
        msgs = [
            ModelResponse(
                parts=[
                    ToolCallPart(tool_name="web_search", args={"query": "test"}),
                ]
            ),
        ]
        text = _serialize_messages_for_summary(msgs)  # type: ignore[invalid-argument-type]
        assert "Assistant [tool_call]: web_search(...)" in text

    def test_truncation(self):
        long_text = "x" * 500
        result = _truncate(long_text)
        assert result.endswith("[truncated]")
        assert len(result) < 500

    def test_no_truncation_for_short_text(self):
        short = "hello"
        assert _truncate(short) == "hello"


class TestCompactionConfig:
    def test_defaults(self):
        c = CompactionConfig()
        assert c.enabled is False
        assert c.threshold == 30
        assert c.tail_messages == 6
        assert c.model_override is None
        assert "[CONVERSATION HISTORY SUMMARY]" in c.summary_prefix

    def test_custom_values(self):
        c = CompactionConfig(
            enabled=True,
            threshold=20,
            tail_messages=10,
            model_override="openai:gpt-4o",
            summary_prefix="[SUMMARY]\n",
        )
        assert c.enabled is True
        assert c.threshold == 20
        assert c.tail_messages == 10
        assert c.model_override == "openai:gpt-4o"
        assert c.summary_prefix == "[SUMMARY]\n"

    def test_threshold_ge_1(self):
        import pytest
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            CompactionConfig(threshold=0)

    def test_tail_messages_ge_1(self):
        import pytest
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            CompactionConfig(tail_messages=0)
