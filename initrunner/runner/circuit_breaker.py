"""Thread-safe circuit breaker for daemon trigger dispatch."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from enum import StrEnum

from initrunner.agent.executor_models import ErrorCategory
from initrunner.agent.schema.guardrails import CircuitBreakerConfig

# Error categories that indicate provider health problems.
# TIMEOUT is excluded: sync timeouts don't cancel the underlying model call,
# so retrying creates duplicate in-flight requests.
_PROVIDER_FAILURES = frozenset(
    {
        ErrorCategory.RATE_LIMIT,
        ErrorCategory.SERVER_ERROR,
        ErrorCategory.CONNECTION,
        ErrorCategory.AUTH,
    }
)


class CircuitState(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass(frozen=True, slots=True)
class CircuitTransition:
    old_state: CircuitState
    new_state: CircuitState


class CircuitBreaker:
    """Per-daemon circuit breaker.

    State machine::

        CLOSED  --(failures >= threshold)--> OPEN
        OPEN    --(reset_timeout elapsed)--> HALF_OPEN
        HALF_OPEN --(probe succeeds)-------> CLOSED
        HALF_OPEN --(probe fails)----------> OPEN

    Only errors in ``_PROVIDER_FAILURES`` increment the failure counter.
    All mutations are guarded by a ``threading.Lock``.
    """

    def __init__(self, config: CircuitBreakerConfig) -> None:
        self._config = config
        self._lock = threading.Lock()
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._opened_at = 0.0
        self._half_open_in_flight = False

    # -- public API -----------------------------------------------------------

    @property
    def state(self) -> CircuitState:
        with self._lock:
            self._check_open_to_half_open()
            return self._state

    def allow_request(self) -> tuple[bool, str]:
        """Check whether a new request should be allowed through."""
        with self._lock:
            self._check_open_to_half_open()
            if self._state == CircuitState.CLOSED:
                return True, ""
            if self._state == CircuitState.OPEN:
                elapsed = time.monotonic() - self._opened_at
                remaining = self._config.reset_timeout_seconds - elapsed
                return (
                    False,
                    f"circuit open ({self._failure_count} failures,"
                    f" resets in {max(0, int(remaining))}s)",
                )
            # HALF_OPEN: allow exactly one probe
            if not self._half_open_in_flight:
                self._half_open_in_flight = True
                return True, ""
            return False, "circuit half-open, probe in progress"

    def record_success(self) -> CircuitTransition | None:
        """Record a successful trigger fire. Returns transition if state changed."""
        with self._lock:
            if self._state == CircuitState.HALF_OPEN:
                return self._transition(CircuitState.CLOSED)
            # Reset failure counter on success even in CLOSED state.
            self._failure_count = 0
            return None

    def record_failure(self, category: ErrorCategory) -> CircuitTransition | None:
        """Record a failed trigger fire. Returns transition if state changed."""
        with self._lock:
            if category not in _PROVIDER_FAILURES:
                return None
            self._failure_count += 1
            if self._state == CircuitState.HALF_OPEN:
                return self._transition(CircuitState.OPEN)
            if (
                self._state == CircuitState.CLOSED
                and self._failure_count >= self._config.failure_threshold
            ):
                return self._transition(CircuitState.OPEN)
            return None

    # -- internals ------------------------------------------------------------

    def _check_open_to_half_open(self) -> None:
        """Transition OPEN -> HALF_OPEN if the reset timeout has elapsed. Called under lock."""
        if self._state != CircuitState.OPEN:
            return
        if time.monotonic() - self._opened_at >= self._config.reset_timeout_seconds:
            self._state = CircuitState.HALF_OPEN
            self._half_open_in_flight = False

    def _transition(self, new_state: CircuitState) -> CircuitTransition:
        """Perform a state transition. Called under lock."""
        old = self._state
        self._state = new_state
        if new_state == CircuitState.OPEN:
            self._opened_at = time.monotonic()
            self._half_open_in_flight = False
        elif new_state == CircuitState.CLOSED:
            self._failure_count = 0
            self._half_open_in_flight = False
        elif new_state == CircuitState.HALF_OPEN:
            self._half_open_in_flight = False
        return CircuitTransition(old_state=old, new_state=new_state)
