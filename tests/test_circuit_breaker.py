"""Tests for the circuit breaker state machine."""

from __future__ import annotations

import threading
import time

from initrunner.agent.executor_models import ErrorCategory
from initrunner.agent.schema.guardrails import CircuitBreakerConfig
from initrunner.runner.circuit_breaker import CircuitBreaker, CircuitState, CircuitTransition


def _make_breaker(threshold: int = 3, timeout: int = 60) -> CircuitBreaker:
    return CircuitBreaker(
        CircuitBreakerConfig(failure_threshold=threshold, reset_timeout_seconds=timeout)
    )


class TestClosedState:
    def test_allows_requests(self):
        cb = _make_breaker()
        allowed, _ = cb.allow_request()
        assert allowed

    def test_state_starts_closed(self):
        cb = _make_breaker()
        assert cb.state == CircuitState.CLOSED

    def test_success_returns_none(self):
        cb = _make_breaker()
        assert cb.record_success() is None

    def test_failure_below_threshold_stays_closed(self):
        cb = _make_breaker(threshold=3)
        assert cb.record_failure(ErrorCategory.SERVER_ERROR) is None
        assert cb.record_failure(ErrorCategory.RATE_LIMIT) is None
        assert cb.state == CircuitState.CLOSED

    def test_failure_at_threshold_opens(self):
        cb = _make_breaker(threshold=3)
        cb.record_failure(ErrorCategory.SERVER_ERROR)
        cb.record_failure(ErrorCategory.SERVER_ERROR)
        t = cb.record_failure(ErrorCategory.SERVER_ERROR)
        assert t == CircuitTransition(old_state=CircuitState.CLOSED, new_state=CircuitState.OPEN)
        assert cb.state == CircuitState.OPEN

    def test_success_resets_failure_count(self):
        cb = _make_breaker(threshold=3)
        cb.record_failure(ErrorCategory.SERVER_ERROR)
        cb.record_failure(ErrorCategory.SERVER_ERROR)
        cb.record_success()
        # Two more failures should not trip (counter was reset)
        cb.record_failure(ErrorCategory.SERVER_ERROR)
        cb.record_failure(ErrorCategory.SERVER_ERROR)
        assert cb.state == CircuitState.CLOSED

    def test_mixed_provider_categories_count(self):
        cb = _make_breaker(threshold=3)
        cb.record_failure(ErrorCategory.RATE_LIMIT)
        cb.record_failure(ErrorCategory.CONNECTION)
        t = cb.record_failure(ErrorCategory.AUTH)
        assert t is not None
        assert cb.state == CircuitState.OPEN


class TestCategoryFiltering:
    def test_content_blocked_ignored(self):
        cb = _make_breaker(threshold=1)
        assert cb.record_failure(ErrorCategory.CONTENT_BLOCKED) is None
        assert cb.state == CircuitState.CLOSED

    def test_usage_limit_ignored(self):
        cb = _make_breaker(threshold=1)
        assert cb.record_failure(ErrorCategory.USAGE_LIMIT) is None
        assert cb.state == CircuitState.CLOSED

    def test_unknown_ignored(self):
        cb = _make_breaker(threshold=1)
        assert cb.record_failure(ErrorCategory.UNKNOWN) is None
        assert cb.state == CircuitState.CLOSED

    def test_timeout_ignored(self):
        cb = _make_breaker(threshold=1)
        assert cb.record_failure(ErrorCategory.TIMEOUT) is None
        assert cb.state == CircuitState.CLOSED

    def test_provider_categories_count(self):
        for cat in (
            ErrorCategory.RATE_LIMIT,
            ErrorCategory.SERVER_ERROR,
            ErrorCategory.CONNECTION,
            ErrorCategory.AUTH,
        ):
            cb = _make_breaker(threshold=1)
            t = cb.record_failure(cat)
            assert t is not None, f"{cat} should trip the breaker"
            assert cb.state == CircuitState.OPEN


class TestOpenState:
    def test_rejects_requests(self):
        cb = _make_breaker(threshold=1)
        cb.record_failure(ErrorCategory.SERVER_ERROR)
        allowed, reason = cb.allow_request()
        assert not allowed
        assert "circuit open" in reason

    def test_reason_includes_failure_count(self):
        cb = _make_breaker(threshold=2)
        cb.record_failure(ErrorCategory.SERVER_ERROR)
        cb.record_failure(ErrorCategory.SERVER_ERROR)
        _, reason = cb.allow_request()
        assert "2 failures" in reason


class TestHalfOpenState:
    def test_transition_after_timeout(self):
        cb = _make_breaker(threshold=1, timeout=10)
        cb.record_failure(ErrorCategory.SERVER_ERROR)
        assert cb.state == CircuitState.OPEN
        # Simulate timeout elapsed
        cb._opened_at = time.monotonic() - 11
        assert cb.state == CircuitState.HALF_OPEN

    def test_allows_one_probe(self):
        cb = _make_breaker(threshold=1, timeout=10)
        cb.record_failure(ErrorCategory.SERVER_ERROR)
        cb._opened_at = time.monotonic() - 11
        allowed, _ = cb.allow_request()
        assert allowed

    def test_blocks_second_probe(self):
        cb = _make_breaker(threshold=1, timeout=10)
        cb.record_failure(ErrorCategory.SERVER_ERROR)
        cb._opened_at = time.monotonic() - 11
        cb.allow_request()  # first probe
        allowed, reason = cb.allow_request()
        assert not allowed
        assert "probe in progress" in reason

    def test_probe_success_closes(self):
        cb = _make_breaker(threshold=1, timeout=10)
        cb.record_failure(ErrorCategory.SERVER_ERROR)
        cb._opened_at = time.monotonic() - 11
        cb.allow_request()  # admit probe
        t = cb.record_success()
        assert t == CircuitTransition(
            old_state=CircuitState.HALF_OPEN, new_state=CircuitState.CLOSED
        )
        assert cb.state == CircuitState.CLOSED

    def test_probe_failure_reopens(self):
        cb = _make_breaker(threshold=1, timeout=10)
        cb.record_failure(ErrorCategory.SERVER_ERROR)
        cb._opened_at = time.monotonic() - 11
        cb.allow_request()  # admit probe
        t = cb.record_failure(ErrorCategory.RATE_LIMIT)
        assert t == CircuitTransition(old_state=CircuitState.HALF_OPEN, new_state=CircuitState.OPEN)
        assert cb.state == CircuitState.OPEN

    def test_after_close_allows_requests(self):
        cb = _make_breaker(threshold=1, timeout=10)
        cb.record_failure(ErrorCategory.SERVER_ERROR)
        cb._opened_at = time.monotonic() - 11
        cb.allow_request()
        cb.record_success()
        allowed, _ = cb.allow_request()
        assert allowed


class TestThreadSafety:
    def test_concurrent_failures(self):
        cb = _make_breaker(threshold=50, timeout=60)
        barrier = threading.Barrier(10)

        def worker():
            barrier.wait()
            for _ in range(10):
                cb.record_failure(ErrorCategory.SERVER_ERROR)

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # 100 failures total, threshold 50 -> should be OPEN
        assert cb.state == CircuitState.OPEN

    def test_concurrent_allow_request(self):
        cb = _make_breaker(threshold=1, timeout=10)
        cb.record_failure(ErrorCategory.SERVER_ERROR)
        cb._opened_at = time.monotonic() - 11
        # Half-open: only one probe should be admitted
        results: list[bool] = []
        barrier = threading.Barrier(5)

        def worker():
            barrier.wait()
            allowed, _ = cb.allow_request()
            results.append(allowed)

        threads = [threading.Thread(target=worker) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert sum(results) == 1  # exactly one probe admitted


class TestTransitionDataclass:
    def test_frozen(self):
        t = CircuitTransition(old_state=CircuitState.CLOSED, new_state=CircuitState.OPEN)
        assert t.old_state == CircuitState.CLOSED
        assert t.new_state == CircuitState.OPEN

    def test_equality(self):
        t1 = CircuitTransition(old_state=CircuitState.CLOSED, new_state=CircuitState.OPEN)
        t2 = CircuitTransition(old_state=CircuitState.CLOSED, new_state=CircuitState.OPEN)
        assert t1 == t2
