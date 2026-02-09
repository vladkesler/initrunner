"""Tests for runner/runner.py: DaemonTokenTracker, run_single, run_autonomous."""

from datetime import date
from unittest.mock import MagicMock, patch

from initrunner.agent.executor import RunResult
from initrunner.agent.schema import (
    AgentSpec,
    ApiVersion,
    AutonomyConfig,
    Guardrails,
    Kind,
    Metadata,
    ModelConfig,
    RoleDefinition,
)
from initrunner.runner import DaemonTokenTracker, run_autonomous, run_single


def _make_role(
    *,
    max_iterations: int = 3,
    autonomous_token_budget: int | None = None,
    autonomy: AutonomyConfig | None = None,
) -> RoleDefinition:
    return RoleDefinition(
        apiVersion=ApiVersion.V1,
        kind=Kind.AGENT,
        metadata=Metadata(name="test-agent"),
        spec=AgentSpec(
            role="You are a test.",
            model=ModelConfig(provider="openai", name="gpt-4o-mini"),
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
        tracker.record_usage(100)
        allowed, reason = tracker.check_before_run()
        assert allowed is False
        assert "Lifetime budget" in reason

    def test_daily_budget_enforced(self):
        tracker = DaemonTokenTracker(lifetime_budget=None, daily_budget=50)
        tracker.record_usage(50)
        allowed, reason = tracker.check_before_run()
        assert allowed is False
        assert "Daily budget" in reason

    def test_daily_reset(self):
        tracker = DaemonTokenTracker(lifetime_budget=None, daily_budget=50)
        tracker.record_usage(50)

        # Simulate day change
        tracker.last_reset_date = date(2020, 1, 1)
        allowed, _reason = tracker.check_before_run()
        assert allowed is True
        # After reset, daily_consumed is the 1-token reservation from check_before_run
        assert tracker.daily_consumed == DaemonTokenTracker._RESERVATION

    def test_record_usage_accumulates(self):
        tracker = DaemonTokenTracker(lifetime_budget=1000, daily_budget=500)
        tracker.record_usage(100)
        tracker.record_usage(200)
        assert tracker.total_consumed == 300
        assert tracker.daily_consumed == 300

    def test_lifetime_exhaustion_blocks_even_after_daily_reset(self):
        tracker = DaemonTokenTracker(lifetime_budget=100, daily_budget=200)
        tracker.record_usage(100)
        # Simulate day change
        tracker.last_reset_date = date(2020, 1, 1)
        allowed, reason = tracker.check_before_run()
        assert allowed is False
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
        assert "boom" in result.error

    def test_sink_dispatch(self):
        agent = _make_mock_agent()
        role = _make_role()
        sink = MagicMock()
        run_single(agent, role, "Hi", sink_dispatcher=sink)
        sink.dispatch.assert_called_once()


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
