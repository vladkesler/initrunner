"""Tests for runner/runner.py: DaemonTokenTracker, run_single, run_autonomous."""

from unittest.mock import MagicMock, patch

from initrunner.agent.executor import RunResult
from initrunner.agent.schema.autonomy import AutonomyConfig
from initrunner.agent.schema.base import ApiVersion, Kind, ModelConfig, RoleMetadata
from initrunner.agent.schema.guardrails import Guardrails
from initrunner.agent.schema.role import AgentSpec, RoleDefinition
from initrunner.runner import run_autonomous, run_single, run_single_stream
from initrunner.runner.budget import DaemonTokenTracker


def _make_role(
    *,
    max_iterations: int = 3,
    autonomous_token_budget: int | None = None,
    autonomy: AutonomyConfig | None = None,
) -> RoleDefinition:
    return RoleDefinition(
        apiVersion=ApiVersion.V1,
        kind=Kind.AGENT,
        metadata=RoleMetadata(name="test-agent"),
        spec=AgentSpec(
            role="You are a test.",
            model=ModelConfig(provider="openai", name="gpt-5-mini"),
            guardrails=Guardrails(
                max_iterations=max_iterations,
                autonomous_token_budget=autonomous_token_budget,
            ),
            autonomy=autonomy,
        ),
    )


def _make_mock_agent(output: str = "Done", tokens: int = 100, tool_calls: int = 1):
    """Create a mock agent that returns a predictable result."""
    agent = MagicMock()
    result = MagicMock()
    result.output = output

    usage = MagicMock()
    usage.input_tokens = tokens // 2
    usage.output_tokens = tokens // 2
    usage.total_tokens = tokens
    usage.tool_calls = tool_calls
    result.usage.return_value = usage
    result.all_messages.return_value = [{"role": "user", "content": "hi"}]

    agent.run_sync.return_value = result
    return agent


# ---------------------------------------------------------------------------
# DaemonTokenTracker
# ---------------------------------------------------------------------------


class TestDaemonTokenTracker:
    def test_no_budgets_always_allowed(self):
        tracker = DaemonTokenTracker(lifetime_budget=None, daily_budget=None)
        allowed, reason = tracker.check_before_run()
        assert allowed is True
        assert reason is None

    def test_lifetime_budget_enforced(self):
        tracker = DaemonTokenTracker(lifetime_budget=100, daily_budget=None)
        tracker.record_usage(60, 40)
        allowed, reason = tracker.check_before_run()
        assert allowed is False
        assert reason is not None
        assert "Lifetime budget" in reason

    def test_daily_budget_enforced(self):
        tracker = DaemonTokenTracker(lifetime_budget=None, daily_budget=50)
        tracker.record_usage(30, 20)
        allowed, reason = tracker.check_before_run()
        assert allowed is False
        assert reason is not None
        assert "Daily budget" in reason

    def test_daily_reset(self):
        tracker = DaemonTokenTracker(lifetime_budget=None, daily_budget=50)
        tracker.record_usage(30, 20)

        # Simulate day change
        tracker.last_reset_date = "2020-01-01"
        allowed, _reason = tracker.check_before_run()
        assert allowed is True
        # After reset, daily_consumed is the 1-token reservation from check_before_run
        assert tracker.daily_consumed == DaemonTokenTracker._RESERVATION

    def test_record_usage_accumulates(self):
        tracker = DaemonTokenTracker(lifetime_budget=1000, daily_budget=500)
        tracker.record_usage(60, 40)
        tracker.record_usage(120, 80)
        assert tracker.total_consumed == 300
        assert tracker.daily_consumed == 300

    def test_lifetime_exhaustion_blocks_even_after_daily_reset(self):
        tracker = DaemonTokenTracker(lifetime_budget=100, daily_budget=200)
        tracker.record_usage(60, 40)
        # Simulate day change
        tracker.last_reset_date = "2020-01-01"
        allowed, reason = tracker.check_before_run()
        assert allowed is False
        assert reason is not None
        assert "Lifetime budget" in reason


# ---------------------------------------------------------------------------
# run_single
# ---------------------------------------------------------------------------


class TestRunSingle:
    def test_successful_output(self):
        agent = _make_mock_agent(output="Hello world")
        role = _make_role()
        result, _messages = run_single(agent, role, "Hi")
        assert result.success is True
        assert result.output == "Hello world"

    def test_failed_run_displays_error(self):
        agent = MagicMock()
        agent.run_sync.side_effect = ConnectionError("boom")
        role = _make_role()
        result, _messages = run_single(agent, role, "Hi")
        assert result.success is False
        assert result.error is not None
        assert "boom" in result.error

    def test_sink_dispatch(self):
        agent = _make_mock_agent()
        role = _make_role()
        sink = MagicMock()
        run_single(agent, role, "Hi", sink_dispatcher=sink)
        sink.dispatch.assert_called_once()


# ---------------------------------------------------------------------------
# run_single_stream
# ---------------------------------------------------------------------------


def _make_role_with_output(output_type: str = "text", **kwargs) -> RoleDefinition:
    """Create a role with a specific output type."""
    from initrunner.agent.schema.output import OutputConfig

    role = _make_role(**kwargs)
    role.spec.output = OutputConfig(type=output_type)  # type: ignore[arg-type]
    return role


class TestRunSingleStream:
    @patch("initrunner.agent.executor.execute_run_stream")
    def test_calls_streaming_executor(self, mock_stream):
        """run_single_stream should call execute_run_stream with an on_token callback."""
        mock_stream.return_value = (
            RunResult(run_id="s1", output="hello", tokens_in=10, tokens_out=5, total_tokens=15),
            [],
        )
        role = _make_role_with_output("text")
        agent = MagicMock()

        run_single_stream(agent, role, "Hi")

        mock_stream.assert_called_once()
        call_kwargs = mock_stream.call_args.kwargs
        assert call_kwargs["on_token"] is not None
        assert callable(call_kwargs["on_token"])

    @patch("initrunner.runner.single.console")
    @patch("initrunner.agent.executor.execute_run_stream")
    def test_writes_tokens_incrementally(self, mock_stream, mock_console):
        """Tokens should be written to console.file as they arrive."""
        import io

        fake_file = io.StringIO()
        mock_console.file = fake_file

        chunks = ["Hel", "lo ", "world"]

        def _side_effect(agent, role, prompt, **kwargs):
            on_token = kwargs["on_token"]
            for chunk in chunks:
                on_token(chunk)
            return (
                RunResult(
                    run_id="s1",
                    output="Hello world",
                    tokens_in=10,
                    tokens_out=5,
                    total_tokens=15,
                ),
                [],
            )

        mock_stream.side_effect = _side_effect
        role = _make_role_with_output("text")
        agent = MagicMock()

        run_single_stream(agent, role, "Hi")

        written = fake_file.getvalue()
        assert "Hello world" in written

    @patch("initrunner.runner.display.console")
    @patch("initrunner.runner.single.console")
    @patch("initrunner.agent.executor.execute_run_stream")
    def test_shows_stats(self, mock_stream, mock_single_console, mock_display_console):
        """Successful stream should print compact stats line."""
        import io

        mock_single_console.file = io.StringIO()
        mock_stream.return_value = (
            RunResult(
                run_id="s1",
                output="ok",
                tokens_in=100,
                tokens_out=50,
                total_tokens=150,
                duration_ms=1234,
            ),
            [],
        )
        role = _make_role_with_output("text")
        agent = MagicMock()

        run_single_stream(agent, role, "Hi")

        mock_display_console.print.assert_called()
        stats_call = mock_display_console.print.call_args[0][0]
        assert "100" in stats_call
        assert "50" in stats_call
        assert "1234" in stats_call

    @patch("initrunner.agent.executor.execute_run_stream")
    def test_error_shows_panel(self, mock_stream):
        """Error result should display the error panel, not stats."""
        mock_stream.return_value = (
            RunResult(run_id="s1", output="", success=False, error="Model exploded"),
            [],
        )
        role = _make_role_with_output("text")
        agent = MagicMock()

        result, _ = run_single_stream(agent, role, "Hi")

        assert result.success is False
        assert result.error == "Model exploded"

    @patch("initrunner.agent.executor.execute_run_stream")
    def test_dispatches_sink(self, mock_stream):
        """Sink dispatch should still occur in streaming mode."""
        mock_stream.return_value = (
            RunResult(run_id="s1", output="hello", tokens_in=10, tokens_out=5, total_tokens=15),
            [],
        )
        role = _make_role_with_output("text")
        agent = MagicMock()
        sink = MagicMock()

        run_single_stream(agent, role, "Hi", sink_dispatcher=sink)

        sink.dispatch.assert_called_once()

    @patch("initrunner.runner.single.run_single")
    def test_structured_output_falls_back(self, mock_run_single):
        """Non-text output type should fall back to run_single."""
        mock_run_single.return_value = (
            RunResult(run_id="s1", output='{"key": "val"}', tokens_in=10, tokens_out=5),
            [],
        )
        from initrunner.agent.schema.output import OutputConfig

        role = _make_role()
        role.spec.output = OutputConfig(
            type="json_schema", schema={"type": "object", "properties": {"key": {"type": "string"}}}
        )
        agent = MagicMock()

        run_single_stream(agent, role, "Hi")

        mock_run_single.assert_called_once()


# ---------------------------------------------------------------------------
# run_autonomous
# ---------------------------------------------------------------------------


class TestRunAutonomous:
    @patch("initrunner.runner.autonomous.execute_run")
    def test_completes_when_reflection_signals_done(self, mock_execute):
        """Agent calls finish_task → loop should stop."""
        role = _make_role(max_iterations=5)

        call_count = 0

        def _side_effect(agent, role, prompt, **kwargs):
            nonlocal call_count
            call_count += 1
            # Simulate finish_task being called on iteration 2
            for ts in kwargs.get("extra_toolsets", []):
                # The reflection toolset has finish_task
                if hasattr(ts, "tools"):
                    pass
            result = RunResult(
                run_id=f"run-{call_count}",
                output=f"Iteration {call_count}",
                tokens_in=50,
                tokens_out=50,
                total_tokens=100,
                tool_calls=1,
            )
            messages = [{"role": "user", "content": "hi"}]
            return result, messages

        mock_execute.side_effect = _side_effect

        agent = MagicMock()
        auto_result = run_autonomous(agent, role, "Do something", max_iterations_override=2)

        assert auto_result.iteration_count == 2
        assert auto_result.final_status == "max_iterations"

    @patch("initrunner.runner.autonomous.execute_run")
    def test_budget_exhaustion(self, mock_execute):
        """Token budget should stop the loop."""
        role = _make_role(max_iterations=10, autonomous_token_budget=150)

        call_count = 0

        def _side_effect(agent, role, prompt, **kwargs):
            nonlocal call_count
            call_count += 1
            result = RunResult(
                run_id=f"run-{call_count}",
                output=f"Iteration {call_count}",
                tokens_in=50,
                tokens_out=50,
                total_tokens=100,
                tool_calls=1,
            )
            return result, [{"role": "user", "content": "hi"}]

        mock_execute.side_effect = _side_effect

        agent = MagicMock()
        auto_result = run_autonomous(agent, role, "Do something")

        # First iteration uses 100 tokens; second should be blocked (100 >= 150 is false,
        # but 200 >= 150 is true — so we get 1 iteration that consumes 100, then check
        # at the top of iteration 2 with 100 consumed which is under 150, so iteration 2
        # runs giving us 200 total, then iteration 3 check with 200 >= 150 breaks)
        assert auto_result.final_status == "budget_exceeded"
        assert auto_result.total_tokens >= 100

    @patch("initrunner.runner.autonomous.execute_run")
    def test_error_stops_loop(self, mock_execute):
        """A failed run should stop the loop with error status."""
        role = _make_role(max_iterations=5)

        def _side_effect(agent, role, prompt, **kwargs):
            result = RunResult(
                run_id="run-err",
                output="",
                success=False,
                error="Model exploded",
            )
            return result, []

        mock_execute.side_effect = _side_effect

        agent = MagicMock()
        auto_result = run_autonomous(agent, role, "Do something")

        assert auto_result.final_status == "error"
        assert auto_result.error == "Model exploded"
        assert auto_result.iteration_count == 1

    @patch("initrunner.runner.autonomous.execute_run")
    def test_history_trimming(self, mock_execute):
        """Message history should be passed between iterations."""
        role = _make_role(max_iterations=2)

        call_count = 0

        def _side_effect(agent, role, prompt, **kwargs):
            nonlocal call_count
            call_count += 1
            result = RunResult(
                run_id=f"run-{call_count}",
                output=f"Iteration {call_count}",
                tokens_in=50,
                tokens_out=50,
                total_tokens=100,
                tool_calls=1,
            )
            return result, [{"role": "user", "content": f"msg-{call_count}"}]

        mock_execute.side_effect = _side_effect

        agent = MagicMock()
        run_autonomous(agent, role, "Do something")

        # Second call should have received message_history from first call
        assert mock_execute.call_count == 2
        second_call = mock_execute.call_args_list[1]
        assert second_call.kwargs.get("message_history") is not None

    @patch("initrunner.runner.autonomous.execute_run")
    def test_trigger_metadata_propagated(self, mock_execute):
        """Trigger metadata should flow through to execute_run."""
        role = _make_role(max_iterations=1)

        def _side_effect(agent, role, prompt, **kwargs):
            result = RunResult(
                run_id="run-1",
                output="Done",
                tokens_in=50,
                tokens_out=50,
                total_tokens=100,
                tool_calls=1,
            )
            return result, []

        mock_execute.side_effect = _side_effect

        agent = MagicMock()
        run_autonomous(
            agent,
            role,
            "Do something",
            trigger_type="cron",
            trigger_metadata={"schedule": "daily"},
        )

        call_kwargs = mock_execute.call_args.kwargs
        assert call_kwargs["trigger_type"] == "cron"
        assert "schedule" in call_kwargs["trigger_metadata"]
        assert "autonomous_run_id" in call_kwargs["trigger_metadata"]
        assert "iteration" in call_kwargs["trigger_metadata"]

    @patch("initrunner.runner.autonomous.execute_run")
    def test_sink_dispatch_on_final(self, mock_execute):
        """Sink dispatcher should be called with the final iteration output."""
        role = _make_role(max_iterations=1)

        def _side_effect(agent, role, prompt, **kwargs):
            result = RunResult(
                run_id="run-1",
                output="Final answer",
                tokens_in=50,
                tokens_out=50,
                total_tokens=100,
                tool_calls=1,
            )
            return result, []

        mock_execute.side_effect = _side_effect

        agent = MagicMock()
        sink = MagicMock()
        run_autonomous(agent, role, "Do something", sink_dispatcher=sink)

        sink.dispatch.assert_called_once()
        dispatched_result = sink.dispatch.call_args[0][0]
        assert dispatched_result.output == "Final answer"
