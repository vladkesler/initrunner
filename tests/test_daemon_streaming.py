"""Tests for daemon streaming output in _on_trigger_inner."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from initrunner.agent.executor import RunResult
from initrunner.agent.schema.base import ApiVersion, Kind, Metadata, ModelConfig
from initrunner.agent.schema.output import OutputConfig
from initrunner.agent.schema.role import AgentSpec, RoleDefinition
from initrunner.runner.daemon import DaemonRunner
from initrunner.triggers.base import TriggerEvent


def _make_role(output_type: str = "text") -> RoleDefinition:
    return RoleDefinition(
        apiVersion=ApiVersion.V1,
        kind=Kind.AGENT,
        metadata=Metadata(name="test-daemon"),
        spec=AgentSpec(
            role="You are a test.",
            model=ModelConfig(provider="openai", name="gpt-5-mini"),
            output=OutputConfig(type=output_type),  # type: ignore[arg-type]
            triggers=[],
        ),
    )


def _make_event(prompt: str = "hello") -> TriggerEvent:
    return TriggerEvent(trigger_type="webhook", prompt=prompt)


def _make_result(output: str = "done") -> RunResult:
    return RunResult(
        run_id="r1",
        output=output,
        tokens_in=10,
        tokens_out=5,
        total_tokens=15,
        duration_ms=100,
    )


class TestDaemonStreaming:
    @patch("initrunner.runner.daemon.execute_run_stream")
    @patch("initrunner.runner.daemon.execute_run")
    @patch("initrunner.runner.daemon.sys")
    def test_tty_text_uses_streaming(self, mock_sys, mock_execute, mock_stream):
        """TTY + text output should use execute_run_stream."""
        mock_sys.stdout.isatty.return_value = True
        role = _make_role("text")
        result = _make_result()
        mock_stream.return_value = (result, [])

        runner = DaemonRunner(MagicMock(), role)
        runner._on_trigger_inner(_make_event())

        mock_stream.assert_called_once()
        mock_execute.assert_not_called()

    @patch("initrunner.runner.daemon.execute_run_stream")
    @patch("initrunner.runner.daemon.execute_run")
    @patch("initrunner.runner.daemon.sys")
    def test_non_tty_uses_buffered(self, mock_sys, mock_execute, mock_stream):
        """Non-TTY should use execute_run (buffered)."""
        mock_sys.stdout.isatty.return_value = False
        role = _make_role("text")
        result = _make_result()
        mock_execute.return_value = (result, [])

        runner = DaemonRunner(MagicMock(), role)
        runner._on_trigger_inner(_make_event())

        mock_execute.assert_called_once()
        mock_stream.assert_not_called()

    @patch("initrunner.runner.daemon.execute_run_stream")
    @patch("initrunner.runner.daemon.execute_run")
    @patch("initrunner.runner.daemon.sys")
    def test_streaming_preserves_reply_fn(self, mock_sys, mock_execute, mock_stream):
        """reply_fn should still be called with the final output in streaming mode."""
        mock_sys.stdout.isatty.return_value = True
        role = _make_role("text")
        result = _make_result("streamed answer")
        mock_stream.return_value = (result, [])

        reply_fn = MagicMock()
        event = TriggerEvent(trigger_type="webhook", prompt="hello", reply_fn=reply_fn)

        runner = DaemonRunner(MagicMock(), role)
        runner._on_trigger_inner(event)

        reply_fn.assert_called_once_with("streamed answer")

    @patch("initrunner.runner.daemon.execute_run_stream")
    @patch("initrunner.runner.daemon.execute_run")
    @patch("initrunner.runner.daemon.sys")
    def test_streaming_preserves_sink_dispatch(self, mock_sys, mock_execute, mock_stream):
        """Sink dispatch should still occur in streaming mode."""
        mock_sys.stdout.isatty.return_value = True
        role = _make_role("text")
        result = _make_result()
        mock_stream.return_value = (result, [])

        sink = MagicMock()
        runner = DaemonRunner(MagicMock(), role, sink_dispatcher=sink)
        runner._on_trigger_inner(_make_event())

        sink.dispatch.assert_called_once()
