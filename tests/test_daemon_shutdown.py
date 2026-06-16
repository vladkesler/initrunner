"""Tests for DaemonRunner in-flight drain on shutdown (B2)."""

from __future__ import annotations

import threading
import time

from initrunner.runner.daemon import DaemonRunner


def _bare_daemon(grace: float) -> DaemonRunner:
    """A DaemonRunner with only the attributes _drain_in_flight touches.

    Avoids the heavy full __init__ (role/agent/stores) since the drain logic is
    self-contained.
    """
    d = DaemonRunner.__new__(DaemonRunner)
    d._in_flight_cond = threading.Condition()
    d._in_flight_count = 0
    d._SHUTDOWN_GRACE_SECONDS = grace  # type: ignore[attr-defined]
    return d


def test_drain_waits_for_in_flight_then_returns_promptly():
    """Regression: shutdown must actually wait on the in-flight condition (the
    old code printed 'Waiting...' but never blocked, abandoning the run)."""
    d = _bare_daemon(grace=5.0)
    d._in_flight_count = 1

    def _finish():
        time.sleep(0.2)
        with d._in_flight_cond:
            d._in_flight_count = 0
            d._in_flight_cond.notify_all()

    worker = threading.Thread(target=_finish)
    start = time.monotonic()
    worker.start()
    d._drain_in_flight()
    elapsed = time.monotonic() - start
    worker.join()

    assert d._in_flight_count == 0
    # Returned when the run finished (~0.2s), not at the 5s grace deadline.
    assert elapsed < 3.0


def test_drain_returns_at_grace_deadline_when_run_never_finishes():
    d = _bare_daemon(grace=0.3)
    d._in_flight_count = 1  # never decremented

    start = time.monotonic()
    d._drain_in_flight()
    elapsed = time.monotonic() - start

    # Bounded: returns at the grace deadline rather than blocking forever.
    assert 0.2 < elapsed < 2.0


def test_drain_returns_immediately_when_idle():
    d = _bare_daemon(grace=5.0)
    d._in_flight_count = 0
    start = time.monotonic()
    d._drain_in_flight()
    assert time.monotonic() - start < 0.5
