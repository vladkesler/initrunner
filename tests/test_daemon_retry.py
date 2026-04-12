"""Tests for daemon-level retry and circuit breaker integration."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from initrunner.agent.executor import RunResult
from initrunner.agent.executor_models import ErrorCategory
from initrunner.agent.schema.base import ApiVersion, Kind, ModelConfig, RoleMetadata
from initrunner.agent.schema.guardrails import CircuitBreakerConfig, Guardrails, RetryPolicy
from initrunner.agent.schema.output import OutputConfig
from initrunner.agent.schema.role import AgentSpec, RoleDefinition
from initrunner.runner.daemon import _DAEMON_RETRYABLE, DaemonRunner
from initrunner.triggers.base import TriggerEvent


def _make_role(
    *,
    max_attempts: int = 1,
    circuit_breaker: CircuitBreakerConfig | None = None,
) -> RoleDefinition:
    return RoleDefinition(
        apiVersion=ApiVersion.V1,
        kind=Kind.AGENT,
        metadata=RoleMetadata(name="test-retry"),
        spec=AgentSpec(
            role="You are a test.",
            model=ModelConfig(provider="openai", name="gpt-5-mini"),
            output=OutputConfig(type="text"),  # type: ignore[arg-type]
            triggers=[],
            guardrails=Guardrails(
                retry_policy=RetryPolicy(
                    max_attempts=max_attempts,
                    backoff_base_seconds=0.5,
                    backoff_max_seconds=1.0,
                ),
                circuit_breaker=circuit_breaker,
            ),
        ),
    )


def _make_event(prompt: str = "hello") -> TriggerEvent:
    return TriggerEvent(trigger_type="webhook", prompt=prompt)


def _make_result(
    *,
    success: bool = True,
    error_category: ErrorCategory | None = None,
    tokens_in: int = 10,
    tokens_out: int = 5,
) -> RunResult:
    return RunResult(
        run_id="r1",
        output="done" if success else "",
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        total_tokens=tokens_in + tokens_out,
        duration_ms=100,
        success=success,
        error="test error" if not success else None,
        error_category=error_category,
    )


class TestRetryLoop:
    @patch("initrunner.runner.daemon.execute_run")
    @patch("initrunner.runner.daemon.sys")
    def test_no_retry_on_success(self, mock_sys, mock_execute):
        mock_sys.stdout.isatty.return_value = False
        role = _make_role(max_attempts=3)
        mock_execute.return_value = (_make_result(), [])

        runner = DaemonRunner(MagicMock(), role)
        runner._on_trigger_inner(_make_event())

        assert mock_execute.call_count == 1

    @patch("initrunner.runner.daemon.time")
    @patch("initrunner.runner.daemon.execute_run")
    @patch("initrunner.runner.daemon.sys")
    def test_retries_on_server_error(self, mock_sys, mock_execute, mock_time):
        mock_sys.stdout.isatty.return_value = False
        mock_time.sleep = MagicMock()
        role = _make_role(max_attempts=3)

        fail = _make_result(success=False, error_category=ErrorCategory.SERVER_ERROR)
        ok = _make_result()
        mock_execute.side_effect = [(fail, []), (ok, [])]

        runner = DaemonRunner(MagicMock(), role)
        runner._on_trigger_inner(_make_event())

        assert mock_execute.call_count == 2
        mock_time.sleep.assert_called_once()

    @patch("initrunner.runner.daemon.execute_run")
    @patch("initrunner.runner.daemon.sys")
    def test_no_retry_on_content_blocked(self, mock_sys, mock_execute):
        mock_sys.stdout.isatty.return_value = False
        role = _make_role(max_attempts=3)
        fail = _make_result(success=False, error_category=ErrorCategory.CONTENT_BLOCKED)
        mock_execute.return_value = (fail, [])

        runner = DaemonRunner(MagicMock(), role)
        runner._on_trigger_inner(_make_event())

        assert mock_execute.call_count == 1

    @patch("initrunner.runner.daemon.execute_run")
    @patch("initrunner.runner.daemon.sys")
    def test_no_retry_on_timeout(self, mock_sys, mock_execute):
        """TIMEOUT is excluded from daemon-level retry."""
        mock_sys.stdout.isatty.return_value = False
        role = _make_role(max_attempts=3)
        fail = _make_result(success=False, error_category=ErrorCategory.TIMEOUT)
        mock_execute.return_value = (fail, [])

        runner = DaemonRunner(MagicMock(), role)
        runner._on_trigger_inner(_make_event())

        assert mock_execute.call_count == 1

    @patch("initrunner.runner.daemon.time")
    @patch("initrunner.runner.daemon.execute_run")
    @patch("initrunner.runner.daemon.sys")
    def test_exhausts_all_attempts(self, mock_sys, mock_execute, mock_time):
        mock_sys.stdout.isatty.return_value = False
        mock_time.sleep = MagicMock()
        role = _make_role(max_attempts=3)
        fail = _make_result(success=False, error_category=ErrorCategory.RATE_LIMIT)
        mock_execute.return_value = (fail, [])

        runner = DaemonRunner(MagicMock(), role)
        runner._on_trigger_inner(_make_event())

        assert mock_execute.call_count == 3
        assert mock_time.sleep.call_count == 2

    @patch("initrunner.runner.daemon.execute_run")
    @patch("initrunner.runner.daemon.sys")
    def test_default_no_retry(self, mock_sys, mock_execute):
        """Default max_attempts=1 means no retry."""
        mock_sys.stdout.isatty.return_value = False
        role = _make_role(max_attempts=1)
        fail = _make_result(success=False, error_category=ErrorCategory.SERVER_ERROR)
        mock_execute.return_value = (fail, [])

        runner = DaemonRunner(MagicMock(), role)
        runner._on_trigger_inner(_make_event())

        assert mock_execute.call_count == 1


class TestPerAttemptUsage:
    @patch("initrunner.runner.daemon.time")
    @patch("initrunner.runner.daemon.execute_run")
    @patch("initrunner.runner.daemon.sys")
    def test_tracker_accumulates_across_retries(self, mock_sys, mock_execute, mock_time):
        mock_sys.stdout.isatty.return_value = False
        mock_time.sleep = MagicMock()
        role = _make_role(max_attempts=2)

        fail = _make_result(
            success=False, error_category=ErrorCategory.CONNECTION, tokens_in=50, tokens_out=25
        )
        ok = _make_result(tokens_in=100, tokens_out=50)
        mock_execute.side_effect = [(fail, []), (ok, [])]

        runner = DaemonRunner(MagicMock(), role)
        runner._on_trigger_inner(_make_event())

        # Total usage should be 150 in + 75 out = 225 (both attempts counted)
        assert runner._tracker.total_consumed == 225


class TestCircuitBreakerIntegration:
    @patch("initrunner.runner.daemon.execute_run")
    @patch("initrunner.runner.daemon.sys")
    def test_success_records_with_breaker(self, mock_sys, mock_execute):
        mock_sys.stdout.isatty.return_value = False
        role = _make_role(circuit_breaker=CircuitBreakerConfig(failure_threshold=3))
        mock_execute.return_value = (_make_result(), [])

        runner = DaemonRunner(MagicMock(), role)
        assert runner._circuit_breaker is not None
        runner._on_trigger_inner(_make_event())

        # Success should reset failure count (no transition from CLOSED)
        from initrunner.runner.circuit_breaker import CircuitState

        assert runner._circuit_breaker.state == CircuitState.CLOSED

    @patch("initrunner.runner.daemon.execute_run")
    @patch("initrunner.runner.daemon.sys")
    def test_failures_trip_breaker(self, mock_sys, mock_execute):
        mock_sys.stdout.isatty.return_value = False
        role = _make_role(circuit_breaker=CircuitBreakerConfig(failure_threshold=2))
        fail = _make_result(success=False, error_category=ErrorCategory.SERVER_ERROR)
        mock_execute.return_value = (fail, [])

        runner = DaemonRunner(MagicMock(), role)

        runner._on_trigger_inner(_make_event())
        runner._on_trigger_inner(_make_event())

        from initrunner.runner.circuit_breaker import CircuitState

        assert runner._circuit_breaker is not None
        assert runner._circuit_breaker.state == CircuitState.OPEN

    @patch("initrunner.runner.daemon.execute_run")
    @patch("initrunner.runner.daemon.sys")
    def test_open_breaker_skips_trigger(self, mock_sys, mock_execute):
        mock_sys.stdout.isatty.return_value = False
        role = _make_role(circuit_breaker=CircuitBreakerConfig(failure_threshold=1))
        fail = _make_result(success=False, error_category=ErrorCategory.SERVER_ERROR)
        mock_execute.return_value = (fail, [])

        runner = DaemonRunner(MagicMock(), role)

        # First trigger: fails and trips breaker
        runner._on_trigger(_make_event())
        assert mock_execute.call_count == 1

        # Second trigger: circuit open, should be skipped
        runner._on_trigger(_make_event())
        assert mock_execute.call_count == 1  # not called again

    @patch("initrunner.runner.daemon.execute_run")
    @patch("initrunner.runner.daemon.sys")
    def test_breaker_records_after_retry_loop(self, mock_sys, mock_execute):
        """Breaker records ONE failure per trigger fire, not per retry attempt."""
        mock_sys.stdout.isatty.return_value = False
        role = _make_role(
            max_attempts=3,
            circuit_breaker=CircuitBreakerConfig(failure_threshold=3),
        )
        fail = _make_result(success=False, error_category=ErrorCategory.SERVER_ERROR)
        mock_execute.return_value = (fail, [])

        runner = DaemonRunner(MagicMock(), role)

        # One trigger fire with 3 retry attempts -- should count as 1 failure
        runner._on_trigger_inner(_make_event())

        from initrunner.runner.circuit_breaker import CircuitState

        # threshold=3, but only 1 failure recorded, so still CLOSED
        assert runner._circuit_breaker is not None
        assert runner._circuit_breaker.state == CircuitState.CLOSED
        assert runner._circuit_breaker._failure_count == 1

    @patch("initrunner.runner.daemon.execute_run")
    @patch("initrunner.runner.daemon.sys")
    def test_non_provider_errors_dont_trip_breaker(self, mock_sys, mock_execute):
        mock_sys.stdout.isatty.return_value = False
        role = _make_role(circuit_breaker=CircuitBreakerConfig(failure_threshold=1))
        fail = _make_result(success=False, error_category=ErrorCategory.CONTENT_BLOCKED)
        mock_execute.return_value = (fail, [])

        runner = DaemonRunner(MagicMock(), role)
        runner._on_trigger_inner(_make_event())

        from initrunner.runner.circuit_breaker import CircuitState

        assert runner._circuit_breaker is not None
        assert runner._circuit_breaker.state == CircuitState.CLOSED


class TestRetryableCategories:
    def test_retryable_set(self):
        assert ErrorCategory.RATE_LIMIT in _DAEMON_RETRYABLE
        assert ErrorCategory.SERVER_ERROR in _DAEMON_RETRYABLE
        assert ErrorCategory.CONNECTION in _DAEMON_RETRYABLE

    def test_non_retryable(self):
        assert ErrorCategory.TIMEOUT not in _DAEMON_RETRYABLE
        assert ErrorCategory.AUTH not in _DAEMON_RETRYABLE
        assert ErrorCategory.CONTENT_BLOCKED not in _DAEMON_RETRYABLE
        assert ErrorCategory.USAGE_LIMIT not in _DAEMON_RETRYABLE
        assert ErrorCategory.UNKNOWN not in _DAEMON_RETRYABLE


class TestSchemaDefaults:
    def test_retry_policy_defaults(self):
        g = Guardrails()
        assert g.retry_policy.max_attempts == 1
        assert g.retry_policy.backoff_base_seconds == 2.0
        assert g.retry_policy.backoff_max_seconds == 30.0

    def test_circuit_breaker_disabled_by_default(self):
        g = Guardrails()
        assert g.circuit_breaker is None

    def test_circuit_breaker_from_yaml(self):
        g = Guardrails(
            retry_policy=RetryPolicy(max_attempts=3),
            circuit_breaker=CircuitBreakerConfig(failure_threshold=5, reset_timeout_seconds=120),
        )
        assert g.retry_policy.max_attempts == 3
        assert g.circuit_breaker is not None
        assert g.circuit_breaker.failure_threshold == 5
        assert g.circuit_breaker.reset_timeout_seconds == 120
