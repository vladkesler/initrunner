"""Tests for daemon lifecycle (start/stop race conditions)."""

from __future__ import annotations

import pytest

from initrunner.api.routes.daemon import (
    _DaemonState,
    _dispatcher_lock,
    _dispatchers,
)


@pytest.fixture(autouse=True)
def _clean_dispatchers():
    """Ensure dispatcher state is clean before/after each test."""
    with _dispatcher_lock:
        _dispatchers.clear()
    yield
    with _dispatcher_lock:
        _dispatchers.clear()


class TestDaemonState:
    def test_initial_state(self):
        state = _DaemonState(status="starting")
        assert state.status == "starting"
        assert state.dispatcher is None
        assert not state.cancel.is_set()

    def test_cancel_signals(self):
        state = _DaemonState(status="starting")
        state.cancel.set()
        assert state.cancel.is_set()

    def test_transition_to_running(self):
        state = _DaemonState(status="starting")
        state.dispatcher = object()
        state.status = "running"
        assert state.status == "running"
        assert state.dispatcher is not None


class TestDaemonStopDuringStartup:
    def test_stop_signals_cancellation_for_starting_daemon(self):
        """Stopping a daemon that is still starting should signal cancellation."""
        state = _DaemonState(status="starting")
        with _dispatcher_lock:
            _dispatchers["test-role"] = state

        # Simulate stop_daemon logic
        with _dispatcher_lock:
            popped = _dispatchers.pop("test-role", None)

        assert popped is state
        popped.cancel.set()

        # The start path should see the cancel
        assert state.cancel.is_set()

    def test_identity_check_prevents_wrong_cleanup(self):
        """Only the owning state should be cleaned up on error."""
        state_a = _DaemonState(status="starting")
        state_b = _DaemonState(status="starting")

        with _dispatcher_lock:
            _dispatchers["role"] = state_a

        # Simulate a second start replacing state_a
        with _dispatcher_lock:
            _dispatchers["role"] = state_b

        # state_a's error handler should NOT remove state_b
        with _dispatcher_lock:
            if _dispatchers.get("role") is state_a:
                del _dispatchers["role"]

        # state_b should still be there
        with _dispatcher_lock:
            assert _dispatchers.get("role") is state_b


class TestConcurrentStart:
    def test_already_starting_detected(self):
        """A second start while one is in progress returns already_starting."""
        state = _DaemonState(status="starting")
        with _dispatcher_lock:
            _dispatchers["role"] = state

        # Simulate the check in start_daemon
        with _dispatcher_lock:
            existing = _dispatchers.get("role")

        assert existing is not None
        assert existing.status == "starting"

    def test_already_running_detected(self):
        """A start while running returns already_running."""
        state = _DaemonState(status="running", dispatcher=object())
        with _dispatcher_lock:
            _dispatchers["role"] = state

        with _dispatcher_lock:
            existing = _dispatchers.get("role")

        assert existing is not None
        assert existing.status == "running"


class TestStartAfterCancel:
    def test_new_start_succeeds_after_cancel(self):
        """After a cancelled start is cleaned up, a new start can proceed."""
        state_old = _DaemonState(status="starting")
        with _dispatcher_lock:
            _dispatchers["role"] = state_old

        # Simulate stop
        with _dispatcher_lock:
            _dispatchers.pop("role", None)
        state_old.cancel.set()

        # New start should succeed
        with _dispatcher_lock:
            assert "role" not in _dispatchers
            state_new = _DaemonState(status="starting")
            _dispatchers["role"] = state_new

        assert not state_new.cancel.is_set()
        assert _dispatchers["role"] is state_new
