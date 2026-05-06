"""Streaming executor tests for items #5 and #6 of the PydanticAI upgrade plan.

Covers:
- Sync streaming with structured output no longer raises and routes partials
  to ``on_partial``.
- Sync streaming with text output still fires ``on_token``.
- Async streaming with ``on_event`` set uses the ``run_stream_events()`` path
  and forwards typed events.
- Finalization goes through ``_finalize_run_output`` so BaseModel outputs
  serialize correctly in the streaming path.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import BaseModel


class _AsyncIter:
    """Minimal async iterator over a list of items."""

    def __init__(self, items):
        self._items = list(items)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._items:
            raise StopAsyncIteration
        return self._items.pop(0)


def _async_ctx(stream):
    """Wrap *stream* in an async context manager mock."""
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=stream)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx


def _make_text_role():
    from initrunner.agent.schema.role import RoleDefinition

    return RoleDefinition.model_validate(
        {
            "apiVersion": "initrunner/v1",
            "kind": "Agent",
            "metadata": {"name": "text-role", "description": "text"},
            "spec": {
                "role": "Text agent.",
                "model": {"provider": "openai", "name": "gpt-5-mini"},
                "output": {"type": "text"},
            },
        }
    )


def _make_structured_role():
    from initrunner.agent.schema.role import RoleDefinition

    return RoleDefinition.model_validate(
        {
            "apiVersion": "initrunner/v1",
            "kind": "Agent",
            "metadata": {"name": "structured-role", "description": "structured"},
            "spec": {
                "role": "Structured agent.",
                "model": {"provider": "openai", "name": "gpt-5-mini"},
                "output": {
                    "type": "json_schema",
                    "schema": {
                        "type": "object",
                        "properties": {
                            "status": {"type": "string"},
                            "count": {"type": "integer"},
                        },
                        "required": ["status", "count"],
                    },
                },
            },
        }
    )


class _Sample(BaseModel):
    status: str
    count: int


# ---------------------------------------------------------------------------
# Finalizer reuse
# ---------------------------------------------------------------------------


class TestFinalizerShared:
    def test_finalize_run_output_serializes_basemodel(self):
        from initrunner.agent.executor import RunResult
        from initrunner.agent.executor_output import _finalize_run_output

        role = _make_structured_role()
        result = RunResult(run_id="r1")
        usage = MagicMock(input_tokens=10, output_tokens=20, total_tokens=30, tool_calls=1)
        _finalize_run_output(_Sample(status="ok", count=7), usage, [], result, role)
        assert result.output == '{"status":"ok","count":7}'
        assert result.tokens_in == 10
        assert result.tokens_out == 20
        assert result.tool_calls == 1

    def test_finalize_run_output_serializes_dict(self):
        from initrunner.agent.executor import RunResult
        from initrunner.agent.executor_output import _finalize_run_output

        role = _make_structured_role()
        result = RunResult(run_id="r1")
        usage = MagicMock(input_tokens=1, output_tokens=2, total_tokens=3, tool_calls=0)
        _finalize_run_output({"status": "ok", "count": 7}, usage, [], result, role)
        assert result.output == '{"status": "ok", "count": 7}'

    def test_finalize_run_output_deferred_tool_requests_pauses(self):
        from pydantic_ai import DeferredToolRequests
        from pydantic_ai.messages import ToolCallPart

        from initrunner.agent.executor import RunResult
        from initrunner.agent.executor_output import _finalize_run_output

        role = _make_text_role()
        result = RunResult(run_id="r1")
        usage = MagicMock(input_tokens=0, output_tokens=0, total_tokens=0, tool_calls=0)
        deferred = DeferredToolRequests(
            approvals=[ToolCallPart(tool_call_id="tc-1", tool_name="shell", args='{"cmd":"ls"}')]
        )
        _finalize_run_output(deferred, usage, [], result, role)
        assert result.status == "paused"
        assert len(result.pending_approvals) == 1
        assert result.pending_approvals[0].tool_name == "shell"


# ---------------------------------------------------------------------------
# Sync streaming: structured output
# ---------------------------------------------------------------------------


class TestSyncStreamingStructured:
    def test_structured_streaming_invokes_on_partial_and_finalizes(self):
        """Structured role: on_partial fires per partial; final validated
        model flows through _finalize_run_output."""
        from initrunner.agent.executor import execute_run_stream

        role = _make_structured_role()
        partials_seen: list = []

        partial_1 = _Sample(status="ok", count=1)
        partial_2 = _Sample(status="ok", count=2)
        final = _Sample(status="done", count=5)

        stream = MagicMock()
        stream.stream_output = MagicMock(return_value=_AsyncIter([partial_1, partial_2]))
        stream.stream_text = MagicMock(return_value=_AsyncIter([]))
        stream.all_messages = MagicMock(return_value=[])
        stream.usage = MagicMock(
            return_value=MagicMock(input_tokens=3, output_tokens=4, total_tokens=7, tool_calls=0)
        )
        stream.get_output = AsyncMock(return_value=final)

        agent = MagicMock()
        agent.run_stream = MagicMock(return_value=_async_ctx(stream))

        with patch("initrunner.agent.executor._prepare_run") as mock_prep:
            mock_prep.return_value = ("run-id", MagicMock(), {}, None)

            result, _msgs = execute_run_stream(
                agent,
                role,
                "prompt",
                on_partial=partials_seen.append,
                skip_input_validation=True,
            )

        assert partials_seen == [partial_1, partial_2]
        # Final validated model should be serialized as JSON in result.output
        assert '"status":"done"' in result.output
        assert '"count":5' in result.output
        # stream_text should NOT have been called for a structured role
        stream.stream_text.assert_not_called()

    def test_text_streaming_still_invokes_on_token(self):
        """Text role: on_token fires per delta; finalizer writes joined
        text. stream_output is not used."""
        from initrunner.agent.executor import execute_run_stream

        role = _make_text_role()
        tokens_seen: list[str] = []

        stream = MagicMock()
        stream.stream_text = MagicMock(return_value=_AsyncIter(["Hello ", "world"]))
        stream.stream_output = MagicMock(return_value=_AsyncIter([]))
        stream.all_messages = MagicMock(return_value=[])
        stream.usage = MagicMock(
            return_value=MagicMock(input_tokens=1, output_tokens=2, total_tokens=3, tool_calls=0)
        )
        stream.get_output = AsyncMock(return_value="Hello world")

        agent = MagicMock()
        agent.run_stream = MagicMock(return_value=_async_ctx(stream))

        with patch("initrunner.agent.executor._prepare_run") as mock_prep:
            mock_prep.return_value = ("run-id", MagicMock(), {}, None)

            result, _msgs = execute_run_stream(
                agent, role, "prompt", on_token=tokens_seen.append, skip_input_validation=True
            )

        assert tokens_seen == ["Hello ", "world"]
        assert result.output == "Hello world"
        stream.stream_output.assert_not_called()


# ---------------------------------------------------------------------------
# Async streaming: on_event uses run_stream_events()
# ---------------------------------------------------------------------------


class TestAsyncStreamingEvents:
    @pytest.mark.asyncio
    async def test_on_event_receives_events_and_finalizes_from_result(self):
        """When on_event is set, async path uses run_stream_events().

        The final AgentRunResultEvent.result flows through the canonical
        finalizer. on_token still fires for text deltas inside
        PartDeltaEvent.
        """
        from pydantic_ai import AgentRunResultEvent
        from pydantic_ai.messages import PartDeltaEvent, PartStartEvent, TextPartDelta

        from initrunner.agent.executor import execute_run_stream_async

        role = _make_text_role()

        start = PartStartEvent(index=0, part=MagicMock())
        delta_1 = PartDeltaEvent(index=0, delta=TextPartDelta(content_delta="Hello "))
        delta_2 = PartDeltaEvent(index=0, delta=TextPartDelta(content_delta="world"))

        fake_agent_result = MagicMock()
        fake_agent_result.output = "Hello world"
        fake_agent_result.usage = MagicMock(
            return_value=MagicMock(input_tokens=1, output_tokens=2, total_tokens=3, tool_calls=0)
        )
        fake_agent_result.all_messages = MagicMock(return_value=[])
        final_event = AgentRunResultEvent(result=fake_agent_result)

        events_to_yield = [start, delta_1, delta_2, final_event]

        async def fake_run_stream_events(*_args, **_kwargs):
            for ev in events_to_yield:
                yield ev

        agent = MagicMock()
        agent.run_stream_events = fake_run_stream_events

        events_seen: list = []
        tokens_seen: list[str] = []

        with patch("initrunner.agent.executor._prepare_run") as mock_prep:
            mock_prep.return_value = ("run-id", MagicMock(), {}, None)

            result, _msgs = await execute_run_stream_async(
                agent,
                role,
                "prompt",
                on_token=tokens_seen.append,
                on_event=events_seen.append,
                skip_input_validation=True,
            )

        assert events_seen == events_to_yield
        assert tokens_seen == ["Hello ", "world"]
        assert result.output == "Hello world"
