"""Tests for the delegate sink."""

from __future__ import annotations

import logging
import queue
import time
from unittest.mock import patch

from initrunner.compose.delegate_sink import DelegateEvent, DelegateSink
from initrunner.sinks.base import SinkPayload


def _make_payload(**overrides) -> SinkPayload:
    defaults = {
        "agent_name": "test-agent",
        "run_id": "abc123",
        "prompt": "hello",
        "output": "world",
        "success": True,
        "error": None,
        "tokens_in": 10,
        "tokens_out": 20,
        "duration_ms": 100,
        "model": "gpt-5-mini",
        "provider": "openai",
        "trigger_type": None,
        "trigger_metadata": {},
        "timestamp": "2025-01-01T00:00:00+00:00",
    }
    defaults.update(overrides)
    return SinkPayload(**defaults)  # type: ignore[arg-type]


class TestDelegateEvent:
    def test_creation(self):
        event = DelegateEvent(
            source_service="a",
            target_service="b",
            prompt="hello",
            source_run_id="run1",
        )
        assert event.source_service == "a"
        assert event.target_service == "b"
        assert event.prompt == "hello"
        assert event.trace == []

    def test_with_trace(self):
        event = DelegateEvent(
            source_service="b",
            target_service="c",
            prompt="output",
            source_run_id="run2",
            trace=["a", "b"],
        )
        assert event.trace == ["a", "b"]

    def test_metadata(self):
        event = DelegateEvent(
            source_service="a",
            target_service="b",
            prompt="hello",
            source_run_id="run1",
            metadata={"key": "value"},
        )
        assert event.metadata == {"key": "value"}


class TestDelegateSink:
    def test_send_enqueues_event(self):
        q: queue.Queue[DelegateEvent] = queue.Queue()
        sink = DelegateSink("source", "target", q)
        payload = _make_payload()

        sink.send(payload)

        assert q.qsize() == 1
        event = q.get_nowait()
        assert event.source_service == "source"
        assert event.target_service == "target"
        assert event.prompt == "world"
        assert event.source_run_id == "abc123"

    def test_send_skips_failed_payload(self):
        q: queue.Queue[DelegateEvent] = queue.Queue()
        sink = DelegateSink("source", "target", q)
        payload = _make_payload(success=False, error="boom")

        sink.send(payload)

        assert q.qsize() == 0

    def test_send_builds_trace(self):
        q: queue.Queue[DelegateEvent] = queue.Queue()
        sink = DelegateSink("source", "target", q)
        payload = _make_payload()

        sink.send(payload)

        event = q.get_nowait()
        assert event.trace == ["source"]
        assert event.metadata["_compose_trace"] == "source"

    def test_send_extends_existing_trace(self):
        q: queue.Queue[DelegateEvent] = queue.Queue()
        sink = DelegateSink("middle", "target", q)
        payload = _make_payload(
            trigger_metadata={
                "_compose_trace": "origin,first",
                "_compose_original_prompt": "original prompt",
            }
        )

        sink.send(payload)

        event = q.get_nowait()
        assert event.trace == ["origin", "first", "middle"]
        assert event.metadata["_compose_original_prompt"] == "original prompt"

    def test_send_preserves_original_prompt(self):
        q: queue.Queue[DelegateEvent] = queue.Queue()
        sink = DelegateSink("source", "target", q)
        payload = _make_payload(prompt="user input", output="agent output")

        sink.send(payload)

        event = q.get_nowait()
        assert event.metadata["_compose_original_prompt"] == "user input"
        assert event.metadata["_compose_source_output"] == "agent output"

    def test_send_drops_on_full_queue(self, caplog):
        q: queue.Queue[DelegateEvent] = queue.Queue(maxsize=1)
        sink = DelegateSink("source", "target", q, timeout_seconds=0)
        payload = _make_payload()

        # Fill queue
        sink.send(payload)
        assert q.qsize() == 1

        # Second send should drop (timeout=0 means immediate)
        ir_logger = logging.getLogger("initrunner")
        ir_logger.addHandler(caplog.handler)
        try:
            with caplog.at_level("WARNING", logger="initrunner.compose.delegate"):
                sink.send(_make_payload(run_id="second"))

            # Should still have only one event
            assert q.qsize() == 1
            assert "Queue full" in caplog.text
            assert sink.dropped_count == 1
        finally:
            ir_logger.removeHandler(caplog.handler)

    def test_send_never_raises(self):
        """Even with a broken queue, send() should not raise."""
        q: queue.Queue[DelegateEvent] = queue.Queue()
        sink = DelegateSink("source", "target", q)

        # Monkeypatch queue.put to raise
        def _raise(*args, **kwargs):
            raise RuntimeError("broken queue")

        q.put = _raise  # type: ignore[invalid-assignment]

        # Should not raise
        sink.send(_make_payload())

    def test_dropped_count_starts_at_zero(self):
        q: queue.Queue[DelegateEvent] = queue.Queue()
        sink = DelegateSink("source", "target", q)
        assert sink.dropped_count == 0

    def test_dropped_count_accumulates(self, caplog):
        q: queue.Queue[DelegateEvent] = queue.Queue(maxsize=1)
        sink = DelegateSink("source", "target", q, timeout_seconds=0)

        # Fill queue
        sink.send(_make_payload())
        assert q.qsize() == 1
        assert sink.dropped_count == 0

        # Send 3 more — all should be dropped
        ir_logger = logging.getLogger("initrunner")
        ir_logger.addHandler(caplog.handler)
        try:
            with caplog.at_level("WARNING", logger="initrunner.compose.delegate"):
                for i in range(3):
                    sink.send(_make_payload(run_id=f"drop{i}"))

            assert q.qsize() == 1
            assert sink.dropped_count == 3
        finally:
            ir_logger.removeHandler(caplog.handler)

    def test_multiple_sends(self):
        q: queue.Queue[DelegateEvent] = queue.Queue()
        sink = DelegateSink("source", "target", q)

        for i in range(5):
            sink.send(_make_payload(run_id=f"run{i}"))

        assert q.qsize() == 5

    def test_source_and_target_properties(self):
        q: queue.Queue[DelegateEvent] = queue.Queue()
        sink = DelegateSink("my-source", "my-target", q)
        assert sink.source_service == "my-source"
        assert sink.target_service == "my-target"

    def test_filtered_count(self):
        q: queue.Queue[DelegateEvent] = queue.Queue()
        sink = DelegateSink("source", "target", q)

        sink.send(_make_payload(success=False, error="boom"))
        sink.send(_make_payload(success=False, error="fail"))

        assert sink.filtered_count == 2
        assert q.qsize() == 0


class TestDelegateSinkAudit:
    def test_delivered_event_logged(self, tmp_path):
        from initrunner.audit.logger import AuditLogger

        db_path = tmp_path / "audit.db"
        q: queue.Queue[DelegateEvent] = queue.Queue()
        with AuditLogger(db_path) as logger:
            sink = DelegateSink("src", "tgt", q, audit_logger=logger)
            sink.send(_make_payload(run_id="r1", output="hello"))
            sink.close()

            events = logger.query_delegate_events()
        assert len(events) == 1
        assert events[0].status == "delivered"
        assert events[0].source_service == "src"
        assert events[0].target_service == "tgt"
        assert events[0].source_run_id == "r1"

    def test_filtered_event_logged_with_payload_error(self, tmp_path):
        from initrunner.audit.logger import AuditLogger

        db_path = tmp_path / "audit.db"
        q: queue.Queue[DelegateEvent] = queue.Queue()
        with AuditLogger(db_path) as logger:
            sink = DelegateSink("src", "tgt", q, audit_logger=logger)
            sink.send(_make_payload(success=False, error="Model API error: timeout", run_id="r2"))
            sink.close()

            events = logger.query_delegate_events()
        assert len(events) == 1
        assert events[0].status == "filtered"
        assert events[0].reason == "Model API error: timeout"

    def test_dropped_event_logged(self, tmp_path):
        from initrunner.audit.logger import AuditLogger

        db_path = tmp_path / "audit.db"
        q: queue.Queue[DelegateEvent] = queue.Queue(maxsize=1)
        with AuditLogger(db_path) as logger:
            sink = DelegateSink("src", "tgt", q, timeout_seconds=0, audit_logger=logger)
            # Fill queue
            sink.send(_make_payload(run_id="r1"))
            # This should be dropped
            sink.send(_make_payload(run_id="r2"))
            sink.close()

            events = logger.query_delegate_events(status="dropped")
        assert len(events) == 1
        assert events[0].reason == "queue_full"

    def test_error_event_logged(self, tmp_path):
        from initrunner.audit.logger import AuditLogger

        db_path = tmp_path / "audit.db"
        q: queue.Queue[DelegateEvent] = queue.Queue()
        with AuditLogger(db_path) as logger:
            sink = DelegateSink("src", "tgt", q, audit_logger=logger)

            # Break the queue to trigger error path
            def _raise(*args, **kwargs):
                raise RuntimeError("broken queue")

            q.put = _raise  # type: ignore[assignment]

            sink.send(_make_payload(run_id="r3"))
            sink.close()

            events = logger.query_delegate_events(status="error")
        assert len(events) == 1
        assert "broken queue" in (events[0].reason or "")

    def test_audit_failure_doesnt_crash_send(self, tmp_path):
        from initrunner.audit.logger import AuditLogger

        db_path = tmp_path / "audit.db"
        audit_logger = AuditLogger(db_path)
        audit_logger.close()  # close to force failures

        q: queue.Queue[DelegateEvent] = queue.Queue()
        sink = DelegateSink("src", "tgt", q, audit_logger=audit_logger)

        # send should not raise even though audit logger is broken
        sink.send(_make_payload(run_id="r1"))
        sink.close()
        assert q.qsize() == 1  # event still delivered

    def test_no_audit_logger_still_works(self):
        q: queue.Queue[DelegateEvent] = queue.Queue()
        sink = DelegateSink("src", "tgt", q)
        sink.send(_make_payload())
        assert q.qsize() == 1
        # No crash, no flush thread
        assert sink._flush_thread is None

    def test_trace_included_in_audit(self, tmp_path):
        from initrunner.audit.logger import AuditLogger

        db_path = tmp_path / "audit.db"
        q: queue.Queue[DelegateEvent] = queue.Queue()
        with AuditLogger(db_path) as logger:
            sink = DelegateSink("middle", "tgt", q, audit_logger=logger)
            sink.send(
                _make_payload(
                    trigger_metadata={
                        "_compose_trace": "origin,first",
                        "_compose_original_prompt": "original",
                    },
                )
            )
            sink.close()

            events = logger.query_delegate_events()
        assert len(events) == 1
        assert events[0].trace == "origin,first,middle"

    def test_buffer_flushes_on_close(self, tmp_path):
        from initrunner.audit.logger import AuditLogger

        db_path = tmp_path / "audit.db"
        q: queue.Queue[DelegateEvent] = queue.Queue()
        with AuditLogger(db_path) as logger:
            sink = DelegateSink("src", "tgt", q, audit_logger=logger)
            for i in range(5):
                sink.send(_make_payload(run_id=f"r{i}"))

            # Events are in the buffer, not yet flushed to DB
            # close() should flush them
            sink.close()

            events = logger.query_delegate_events()
        assert len(events) == 5


class TestCircuitBreaker:
    def test_disabled_by_default(self):
        """threshold=None means unlimited failures without tripping."""
        q: queue.Queue[DelegateEvent] = queue.Queue(maxsize=1)
        sink = DelegateSink("src", "tgt", q, timeout_seconds=0)

        # Fill queue
        sink.send(_make_payload(run_id="r0"))
        assert q.qsize() == 1

        # 100 drops should not trip the circuit
        for i in range(100):
            sink.send(_make_payload(run_id=f"drop{i}"))

        assert sink.dropped_count == 100
        assert sink.circuit_state == "closed"

    def test_trips_after_threshold(self):
        """N consecutive drops -> circuit opens -> subsequent sends rejected."""
        q: queue.Queue[DelegateEvent] = queue.Queue(maxsize=1)
        sink = DelegateSink("src", "tgt", q, timeout_seconds=0, circuit_breaker_threshold=3)

        # Fill queue
        sink.send(_make_payload(run_id="r0"))
        assert q.qsize() == 1

        # 3 drops to trip the circuit
        for i in range(3):
            sink.send(_make_payload(run_id=f"drop{i}"))

        assert sink.circuit_state == "open"
        assert sink.consecutive_failures == 3

        # Next send should be rejected without touching the queue
        initial_dropped = sink.dropped_count
        sink.send(_make_payload(run_id="rejected"))
        assert sink.dropped_count == initial_dropped + 1
        assert q.qsize() == 1  # queue unchanged

    def test_successful_delivery_resets_counter(self):
        """Failures then success -> counter back to 0."""
        q: queue.Queue[DelegateEvent] = queue.Queue(maxsize=2)
        sink = DelegateSink("src", "tgt", q, timeout_seconds=0, circuit_breaker_threshold=5)

        # Fill queue
        sink.send(_make_payload(run_id="r0"))
        sink.send(_make_payload(run_id="r1"))
        assert q.qsize() == 2

        # 3 consecutive failures
        for i in range(3):
            sink.send(_make_payload(run_id=f"drop{i}"))
        assert sink.consecutive_failures == 3
        assert sink.circuit_state == "closed"  # not yet at threshold

        # Drain queue and send a success
        q.get_nowait()
        q.get_nowait()
        sink.send(_make_payload(run_id="success"))
        assert sink.consecutive_failures == 0
        assert sink.circuit_state == "closed"

    def test_half_open_probe_succeeds(self):
        """After reset timeout, one message allowed through; on success -> closed."""
        q: queue.Queue[DelegateEvent] = queue.Queue(maxsize=1)
        sink = DelegateSink(
            "src",
            "tgt",
            q,
            timeout_seconds=0,
            circuit_breaker_threshold=2,
            circuit_breaker_reset_seconds=1,
        )

        # Fill queue and trip circuit
        sink.send(_make_payload(run_id="r0"))
        sink.send(_make_payload(run_id="drop0"))
        sink.send(_make_payload(run_id="drop1"))
        assert sink.circuit_state == "open"

        # Drain queue to allow probe to succeed
        q.get_nowait()

        # Fast-forward past reset timeout
        future = time.monotonic() + 2
        with patch("initrunner.compose.delegate_sink.time.monotonic", return_value=future):
            sink.send(_make_payload(run_id="probe"))

        assert sink.circuit_state == "closed"
        assert sink.consecutive_failures == 0
        assert q.qsize() == 1

    def test_half_open_probe_fails(self):
        """After reset timeout, probe fails -> re-opens circuit."""
        q: queue.Queue[DelegateEvent] = queue.Queue(maxsize=1)
        sink = DelegateSink(
            "src",
            "tgt",
            q,
            timeout_seconds=0,
            circuit_breaker_threshold=2,
            circuit_breaker_reset_seconds=1,
        )

        # Fill queue and trip circuit
        sink.send(_make_payload(run_id="r0"))
        sink.send(_make_payload(run_id="drop0"))
        sink.send(_make_payload(run_id="drop1"))
        assert sink.circuit_state == "open"

        # Queue still full — probe will fail
        future = time.monotonic() + 2
        with patch("initrunner.compose.delegate_sink.time.monotonic", return_value=future):
            sink.send(_make_payload(run_id="probe_fail"))

        assert sink.circuit_state == "open"

    def test_filtered_does_not_count(self):
        """Filtered events don't affect the circuit breaker."""
        q: queue.Queue[DelegateEvent] = queue.Queue(maxsize=1)
        sink = DelegateSink("src", "tgt", q, timeout_seconds=0, circuit_breaker_threshold=3)

        # Fill queue
        sink.send(_make_payload(run_id="r0"))

        # 2 drops
        sink.send(_make_payload(run_id="drop0"))
        sink.send(_make_payload(run_id="drop1"))
        assert sink.consecutive_failures == 2

        # Filtered events should not touch the counter
        for i in range(10):
            sink.send(_make_payload(success=False, error="upstream fail", run_id=f"f{i}"))

        assert sink.consecutive_failures == 2
        assert sink.circuit_state == "closed"

    def test_circuit_open_audit_event(self, tmp_path):
        """Rejected messages logged with status 'circuit_open'."""
        from initrunner.audit.logger import AuditLogger

        db_path = tmp_path / "audit.db"
        q: queue.Queue[DelegateEvent] = queue.Queue(maxsize=1)
        with AuditLogger(db_path) as logger:
            sink = DelegateSink(
                "src",
                "tgt",
                q,
                timeout_seconds=0,
                audit_logger=logger,
                circuit_breaker_threshold=2,
            )

            # Fill queue and trip circuit
            sink.send(_make_payload(run_id="r0"))
            sink.send(_make_payload(run_id="drop0"))
            sink.send(_make_payload(run_id="drop1"))
            assert sink.circuit_state == "open"

            # This should be rejected with circuit_open audit event
            sink.send(_make_payload(run_id="rejected"))
            sink.close()

            events = logger.query_delegate_events(status="circuit_open")
        assert len(events) == 1
        assert events[0].reason == "circuit_breaker_open"
        assert events[0].source_run_id == "rejected"

    def test_error_counts_toward_threshold(self):
        """Generic exceptions also trip the breaker."""
        q: queue.Queue[DelegateEvent] = queue.Queue()
        sink = DelegateSink(
            "src",
            "tgt",
            q,
            circuit_breaker_threshold=2,
        )

        # Monkeypatch queue.put to raise
        def _raise(*args, **kwargs):
            raise RuntimeError("broken queue")

        q.put = _raise  # type: ignore[assignment]

        sink.send(_make_payload(run_id="err0"))
        sink.send(_make_payload(run_id="err1"))

        assert sink.circuit_state == "open"
        assert sink.consecutive_failures == 2

    def test_circuit_state_property(self):
        """Verify property reflects actual state transitions."""
        q: queue.Queue[DelegateEvent] = queue.Queue(maxsize=1)
        sink = DelegateSink(
            "src",
            "tgt",
            q,
            timeout_seconds=0,
            circuit_breaker_threshold=2,
            circuit_breaker_reset_seconds=1,
        )

        # Initial state
        assert sink.circuit_state == "closed"

        # Fill queue and trip
        sink.send(_make_payload(run_id="r0"))
        sink.send(_make_payload(run_id="drop0"))
        sink.send(_make_payload(run_id="drop1"))
        assert sink.circuit_state == "open"

        # Fast-forward past reset timeout — next send transitions to half_open
        # We need to check the state *during* the half-open window
        # Drain queue so probe can succeed
        q.get_nowait()

        future = time.monotonic() + 2
        with patch("initrunner.compose.delegate_sink.time.monotonic", return_value=future):
            sink.send(_make_payload(run_id="probe"))

        assert sink.circuit_state == "closed"
