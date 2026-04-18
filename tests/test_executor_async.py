"""Tests for async executor variants (Phase 2)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from initrunner.agent.executor import (
    RunResult,
    _retry_model_call_async,
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


class TestRetryModelCallAsync:
    @pytest.mark.asyncio
    async def test_succeeds_first_try(self):
        result = await _retry_model_call_async(AsyncMock(return_value=42))
        assert result == 42

    @pytest.mark.asyncio
    async def test_retries_on_retryable_status(self):
        from pydantic_ai.exceptions import ModelHTTPError

        call_count = 0

        async def _fn():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ModelHTTPError(status_code=429, model_name="test", body=b"rate limited")
            return "ok"

        result = await _retry_model_call_async(_fn)
        assert result == "ok"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_raises_non_retryable(self):
        from pydantic_ai.exceptions import ModelHTTPError

        async def _fn():
            raise ModelHTTPError(status_code=400, model_name="test", body=b"bad request")

        with pytest.raises(ModelHTTPError):
            await _retry_model_call_async(_fn)

    @pytest.mark.asyncio
    async def test_calls_on_retry(self):
        from pydantic_ai.exceptions import ModelHTTPError

        retries = []

        call_count = 0

        async def _fn():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise ModelHTTPError(status_code=500, model_name="test", body=b"error")
            return "ok"

        result = await _retry_model_call_async(_fn, on_retry=lambda: retries.append(1))
        assert result == "ok"
        assert len(retries) == 1

    @pytest.mark.asyncio
    async def test_on_retry_not_called_on_terminal_failure(self):
        """on_retry must NOT be called when no further retry will follow."""
        from pydantic_ai.exceptions import ModelHTTPError

        retries = []

        async def _fn():
            raise ModelHTTPError(status_code=429, model_name="test", body=b"rate limited")

        with pytest.raises(ModelHTTPError):
            await _retry_model_call_async(_fn, on_retry=lambda: retries.append(1))

        # 3 attempts total, only 2 retries (before attempts 2 and 3)
        # on_retry should NOT be called on the final (3rd) attempt
        assert len(retries) == 2


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

            def usage(self):
                return FakeUsage()

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


class TestAsyncSkipInputValidationMetadata:
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

        call_kwargs = agent.run.call_args.kwargs
        assert call_kwargs.get("metadata") == {"input_validated": True}

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

        call_kwargs = agent.run.call_args.kwargs
        assert call_kwargs.get("metadata") == {"input_validated": True}


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

    @pytest.mark.asyncio
    async def test_structured_output_raises(self):
        role = _make_role()
        role.spec.output.type = "json_schema"
        agent = MagicMock()

        with pytest.raises(ValueError, match="Streaming is not supported"):
            await execute_run_stream_async(agent, role, "test", skip_input_validation=True)


class TestToolBuildAsync:
    def test_prefer_async_in_context(self):
        from initrunner.agent.tools._registry import ToolBuildContext

        role = _make_role()
        ctx = ToolBuildContext(role=role, prefer_async=True)
        assert ctx.prefer_async is True

        ctx2 = ToolBuildContext(role=role)
        assert ctx2.prefer_async is False

    def test_build_toolsets_passes_prefer_async(self):
        from initrunner.agent.tools._registry import ToolBuildContext
        from initrunner.agent.tools.registry import build_toolsets

        role = _make_role()

        with patch("initrunner.agent.tools.registry.ToolBuildContext") as MockCtx:
            MockCtx.return_value = ToolBuildContext(role=role, prefer_async=True)
            build_toolsets([], role, prefer_async=True)
            call = MockCtx.call_args
            assert call.kwargs["role"] is role
            assert call.kwargs["role_dir"] is None
            assert call.kwargs["prefer_async"] is True
