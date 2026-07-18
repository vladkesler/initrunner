"""Tests for async executor variants (Phase 2)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from initrunner.agent.executor import (
    RunResult,
    execute_run_async,
    execute_run_stream_async,
)


def _make_role():
    from initrunner.agent.schema.role import RoleDefinition

    return RoleDefinition.model_validate(
        {
            "apiVersion": "initrunner/v1",
            "kind": "Agent",
            "metadata": {"name": "test", "description": "test"},
            "spec": {
                "role": "You are a test agent.",
                "model": {"provider": "openai", "name": "gpt-5-mini"},
            },
        }
    )


class TestExecuteRunAsync:
    @pytest.mark.asyncio
    @patch("initrunner.agent.executor._validate_input_or_fail")
    async def test_blocked_input_returns_early(self, mock_validate):
        blocked = RunResult(run_id="blocked", success=False, error="blocked")
        mock_validate.return_value = blocked

        role = _make_role()
        agent = MagicMock()

        result, _msgs = await execute_run_async(agent, role, "test prompt")
        assert result.success is False
        assert result.error == "blocked"
        assert _msgs == []

    @pytest.mark.asyncio
    async def test_successful_run(self):
        role = _make_role()

        @dataclass
        class FakeUsage:
            input_tokens: int = 10
            output_tokens: int = 20
            total_tokens: int = 30
            tool_calls: int = 0

        @dataclass
        class FakeResult:
            output: str = "response text"
            usage: FakeUsage = field(default_factory=FakeUsage)

            def all_messages(self):
                return []

        agent = MagicMock()
        agent.run = AsyncMock(return_value=FakeResult())

        result, _msgs = await execute_run_async(
            agent, role, "test prompt", skip_input_validation=True
        )
        assert result.success is True
        assert result.output == "response text"
        assert result.tokens_in == 10
        assert result.tokens_out == 20
        # usage without cache_hit_ratio (older usage / TestModel) stays None
        assert result.cache_hit_ratio is None

    @pytest.mark.asyncio
    async def test_cache_hit_ratio_surfaced(self):
        """cache_hit_ratio (pydantic-ai 2.13) flows onto the RunResult."""
        role = _make_role()

        @dataclass
        class FakeUsage:
            input_tokens: int = 100
            output_tokens: int = 20
            total_tokens: int = 120
            tool_calls: int = 0
            cache_hit_ratio: float = 0.75

        @dataclass
        class FakeResult:
            output: str = "cached response"
            usage: FakeUsage = field(default_factory=FakeUsage)

            def all_messages(self):
                return []

        agent = MagicMock()
        agent.run = AsyncMock(return_value=FakeResult())

        result, _msgs = await execute_run_async(
            agent, role, "test prompt", skip_input_validation=True
        )
        assert result.cache_hit_ratio == 0.75

        from initrunner.runner.display import _cache_suffix

        assert _cache_suffix(result) == " | cache hit: 75%"
        result.cache_hit_ratio = None
        assert _cache_suffix(result) == ""

    @pytest.mark.asyncio
    async def test_timeout_produces_error(self):
        role = _make_role()
        # Set a very short timeout
        role.spec.guardrails.timeout_seconds = 0.01

        agent = MagicMock()

        async def _slow_run(*args, **kwargs):
            await asyncio.sleep(10)

        agent.run = _slow_run

        result, _msgs = await execute_run_async(agent, role, "test", skip_input_validation=True)
        assert result.success is False
        assert "timed out" in (result.error or "")


class TestAsyncRunMetadata:
    @pytest.mark.asyncio
    async def test_metadata_set_when_skip_true(self):
        role = _make_role()
        agent = MagicMock()
        agent.run = AsyncMock(
            return_value=MagicMock(
                output="ok",
                usage=MagicMock(input_tokens=0, output_tokens=0, total_tokens=0, tool_calls=0),
                all_messages=MagicMock(return_value=[]),
            )
        )

        await execute_run_async(agent, role, "Hello", skip_input_validation=True)

        meta = agent.run.call_args.kwargs.get("metadata")
        assert meta is not None
        assert meta["input_validated"] is True
        assert meta["initrunner.agent_name"] == role.metadata.name
        assert "initrunner.run_id" in meta

    @pytest.mark.asyncio
    async def test_metadata_set_when_preflight_passes(self):
        """When skip_input_validation=False and validation passes, metadata is still set."""
        role = _make_role()
        agent = MagicMock()
        agent.run = AsyncMock(
            return_value=MagicMock(
                output="ok",
                usage=MagicMock(input_tokens=0, output_tokens=0, total_tokens=0, tool_calls=0),
                all_messages=MagicMock(return_value=[]),
            )
        )

        await execute_run_async(agent, role, "Hello", skip_input_validation=False)

        meta = agent.run.call_args.kwargs.get("metadata")
        assert meta is not None
        assert meta["input_validated"] is True
        assert meta["initrunner.agent_name"] == role.metadata.name
        assert "initrunner.run_id" in meta


class TestExecuteRunStreamAsync:
    @pytest.mark.asyncio
    async def test_blocked_input_returns_early(self):
        role = _make_role()
        agent = MagicMock()

        with patch("initrunner.agent.executor._validate_input_or_fail") as mock_val:
            blocked = RunResult(run_id="b1", success=False, error="nope")
            mock_val.return_value = blocked
            result, _msgs = await execute_run_stream_async(agent, role, "test")
            assert result.success is False

    # Streaming with structured output is now supported.
    # See tests/test_executor_streaming.py::TestAsyncStreamingEvents for the
    # full coverage (typed events, on_event callback, run_stream_events path).
