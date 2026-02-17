"""Queue-based inter-service routing sink for compose orchestration."""

from __future__ import annotations

import collections
import queue
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from initrunner._log import get_logger
from initrunner.sinks.base import SinkBase, SinkPayload

if TYPE_CHECKING:
    from initrunner.audit.logger import AuditLogger

logger = get_logger("compose.delegate")

_FLUSH_INTERVAL = 1.0  # seconds
_FLUSH_THRESHOLD = 64  # events
_MAX_DELEGATION_DEPTH = 20


@dataclass
class DelegateEvent:
    """Message passed between compose services via queue."""

    source_service: str
    target_service: str
    prompt: str
    source_run_id: str
    metadata: dict[str, str] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    trace: list[str] = field(default_factory=list)


class DelegateSink(SinkBase):
    """Routes agent output to another service's inbox queue.

    Implements blocking backpressure: if the downstream service is slow,
    the upstream agent blocks on ``queue.put(block=True, timeout=...)``.
    Never raises — timeout results in a warning + drop.

    When an ``audit_logger`` is provided, delegate routing outcomes are
    buffered in a deque and flushed to SQLite by a background thread.
    """

    def __init__(
        self,
        source_service: str,
        target_service: str,
        target_queue: queue.Queue[DelegateEvent],
        timeout_seconds: int = 60,
        *,
        audit_logger: AuditLogger | None = None,
        circuit_breaker_threshold: int | None = None,
        circuit_breaker_reset_seconds: int = 60,
    ) -> None:
        self._source_service = source_service
        self._target_service = target_service
        self._target_queue = target_queue
        self._timeout_seconds = timeout_seconds
        self._audit_logger = audit_logger
        self._counter_lock = threading.Lock()
        self._dropped_count = 0
        self._filtered_count = 0

        # Circuit breaker state
        self._cb_threshold = circuit_breaker_threshold
        self._cb_reset_seconds = circuit_breaker_reset_seconds
        self._consecutive_failures = 0
        self._circuit_state = "closed"
        self._circuit_opened_at: float | None = None

        # Buffered audit event writes
        self._audit_buffer: collections.deque[dict] = collections.deque(maxlen=10_000)
        self._audit_overflow_count = 0
        self._flush_stop = threading.Event()
        self._flush_thread: threading.Thread | None = None
        if self._audit_logger is not None:
            self._flush_thread = threading.Thread(
                target=self._flush_loop, daemon=True, name="delegate-audit-flush"
            )
            self._flush_thread.start()

    @property
    def dropped_count(self) -> int:
        """Number of messages dropped due to full queue."""
        with self._counter_lock:
            return self._dropped_count

    @property
    def filtered_count(self) -> int:
        """Number of messages filtered due to upstream failure."""
        with self._counter_lock:
            return self._filtered_count

    @property
    def circuit_state(self) -> str:
        """Current circuit breaker state: closed, open, or half_open."""
        with self._counter_lock:
            return self._circuit_state

    @property
    def consecutive_failures(self) -> int:
        """Number of consecutive delivery failures."""
        with self._counter_lock:
            return self._consecutive_failures

    @property
    def source_service(self) -> str:
        """Name of the source service."""
        return self._source_service

    @property
    def target_service(self) -> str:
        """Name of the target service."""
        return self._target_service

    @property
    def audit_overflow_count(self) -> int:
        """Number of audit events dropped due to buffer overflow."""
        with self._counter_lock:
            return self._audit_overflow_count

    def _log_event(
        self,
        *,
        status: str,
        source_run_id: str,
        reason: str | None = None,
        trace: str | None = None,
        payload_preview: str = "",
    ) -> None:
        """Buffer an audit event. Never raises."""
        try:
            maxlen = self._audit_buffer.maxlen
            if maxlen is not None and len(self._audit_buffer) >= maxlen:
                with self._counter_lock:
                    self._audit_overflow_count += 1
                    count = self._audit_overflow_count
                if count <= 5 or count % 100 == 0:
                    logger.warning(
                        "Audit buffer full (%d events dropped so far): %s -> %s",
                        count,
                        self._source_service,
                        self._target_service,
                    )
                self.flush()
            self._audit_buffer.append(
                {
                    "source_service": self._source_service,
                    "target_service": self._target_service,
                    "status": status,
                    "source_run_id": source_run_id,
                    "reason": reason,
                    "trace": trace,
                    "payload_preview": payload_preview,
                }
            )
        except Exception:
            logger.debug("Failed to buffer audit event", exc_info=True)

    def _flush_loop(self) -> None:
        """Background loop: flush audit buffer every interval or at threshold."""
        while not self._flush_stop.is_set():
            self._flush_stop.wait(timeout=_FLUSH_INTERVAL)
            self.flush()

    def flush(self) -> None:
        """Drain buffered audit events to the audit logger."""
        if self._audit_logger is None:
            return
        while self._audit_buffer:
            try:
                event = self._audit_buffer.popleft()
            except IndexError:
                break
            try:
                self._audit_logger.log_delegate_event(**event)
            except Exception:
                logger.debug("Failed to flush audit event", exc_info=True)

    def _check_circuit(self) -> bool:
        """Check circuit breaker state. Returns True if message should be allowed.

        Must be called with ``_counter_lock`` held.
        """
        if self._cb_threshold is None:
            return True

        if self._circuit_state == "closed":
            return True

        if self._circuit_state == "open":
            if (
                self._circuit_opened_at is not None
                and time.monotonic() - self._circuit_opened_at >= self._cb_reset_seconds
            ):
                self._circuit_state = "half_open"
                logger.info(
                    "Circuit half-open: %s -> %s (allowing probe)",
                    self._source_service,
                    self._target_service,
                )
                return True
            return False

        # half_open — allow the probe through
        return True

    def _record_success(self) -> None:
        """Record a successful delivery. Must be called with ``_counter_lock`` held."""
        if self._cb_threshold is None:
            return
        was_half_open = self._circuit_state == "half_open"
        self._consecutive_failures = 0
        if was_half_open:
            self._circuit_state = "closed"
            self._circuit_opened_at = None
            logger.info(
                "Circuit closed: %s -> %s (probe succeeded)",
                self._source_service,
                self._target_service,
            )

    def _record_failure(self) -> None:
        """Record a delivery failure. Must be called with ``_counter_lock`` held."""
        if self._cb_threshold is None:
            return
        self._consecutive_failures += 1
        if self._circuit_state == "half_open":
            # Probe failed — re-open
            self._circuit_state = "open"
            self._circuit_opened_at = time.monotonic()
            logger.warning(
                "Circuit re-opened: %s -> %s (probe failed)",
                self._source_service,
                self._target_service,
            )
        elif self._consecutive_failures >= self._cb_threshold:
            self._circuit_state = "open"
            self._circuit_opened_at = time.monotonic()
            logger.warning(
                "Circuit open: %s -> %s (%d consecutive failures)",
                self._source_service,
                self._target_service,
                self._consecutive_failures,
            )

    def send(self, payload: SinkPayload) -> None:
        """Enqueue agent output as a DelegateEvent for the target service."""
        try:
            if not payload.success:
                with self._counter_lock:
                    self._filtered_count += 1
                if self._audit_logger is not None:
                    trace_str = payload.trigger_metadata.get("_compose_trace")
                    self._log_event(
                        status="filtered",
                        source_run_id=payload.run_id,
                        reason=payload.error,
                        trace=trace_str,
                        payload_preview=payload.output[:200] if payload.output else "",
                    )
                return

            # Check circuit breaker before attempting delivery
            with self._counter_lock:
                if not self._check_circuit():
                    self._dropped_count += 1
                    logger.warning(
                        "Circuit open: %s -> %s. Message rejected.",
                        self._source_service,
                        self._target_service,
                    )
                    if self._audit_logger is not None:
                        self._log_event(
                            status="circuit_open",
                            source_run_id=payload.run_id,
                            reason="circuit_breaker_open",
                            payload_preview=payload.output[:200] if payload.output else "",
                        )
                    return

            # Build trace from existing metadata or start fresh
            existing_trace = payload.trigger_metadata.get("_compose_trace", "")
            if existing_trace:
                trace = [*existing_trace.split(","), self._source_service]
            else:
                trace = [self._source_service]

            if len(trace) > _MAX_DELEGATION_DEPTH:
                with self._counter_lock:
                    self._dropped_count += 1
                logger.error(
                    "Delegation depth exceeded (%d): %s. Dropping message.",
                    len(trace),
                    " -> ".join(trace),
                )
                if self._audit_logger is not None:
                    self._log_event(
                        status="dropped",
                        source_run_id=payload.run_id,
                        reason=f"delegation_depth_exceeded ({len(trace)})",
                        trace=",".join(trace),
                        payload_preview=payload.output[:200] if payload.output else "",
                    )
                return

            trace_str = ",".join(trace)

            metadata = {
                "_compose_trace": trace_str,
                "_compose_original_prompt": payload.trigger_metadata.get(
                    "_compose_original_prompt", payload.prompt
                ),
                "_compose_source_output": payload.output,
            }

            from initrunner.observability import inject_trace_context

            inject_trace_context(metadata)

            event = DelegateEvent(
                source_service=self._source_service,
                target_service=self._target_service,
                prompt=payload.output,
                source_run_id=payload.run_id,
                metadata=metadata,
                trace=trace,
            )

            self._target_queue.put(event, block=True, timeout=self._timeout_seconds)

            with self._counter_lock:
                self._record_success()

            if self._audit_logger is not None:
                self._log_event(
                    status="delivered",
                    source_run_id=payload.run_id,
                    trace=trace_str,
                    payload_preview=payload.output[:200] if payload.output else "",
                )

        except queue.Full:
            with self._counter_lock:
                self._dropped_count += 1
                self._record_failure()
            logger.warning(
                "Queue full: %s -> %s (timeout=%ds). Message dropped.",
                self._source_service,
                self._target_service,
                self._timeout_seconds,
            )
            if self._audit_logger is not None:
                trace_str = payload.trigger_metadata.get("_compose_trace", "")
                self._log_event(
                    status="dropped",
                    source_run_id=payload.run_id,
                    reason="queue_full",
                    trace=trace_str or None,
                    payload_preview=payload.output[:200] if payload.output else "",
                )
        except Exception as exc:
            with self._counter_lock:
                self._record_failure()
            logger.error(
                "Error routing %s -> %s: %s",
                self._source_service,
                self._target_service,
                exc,
            )
            if self._audit_logger is not None:
                self._log_event(
                    status="error",
                    source_run_id=payload.run_id,
                    reason=str(exc),
                    payload_preview=payload.output[:200] if payload.output else "",
                )

    def close(self) -> None:
        """Stop the flush thread and drain remaining audit events."""
        self._flush_stop.set()
        if self._flush_thread is not None:
            self._flush_thread.join(timeout=5)
            if self._flush_thread.is_alive():
                logger.warning(
                    "Audit flush thread did not stop in time: %s -> %s",
                    self._source_service,
                    self._target_service,
                )
        self.flush()
        with self._counter_lock:
            overflow = self._audit_overflow_count
        if overflow:
            logger.warning(
                "Audit buffer overflowed %d time(s) during lifetime: %s -> %s",
                overflow,
                self._source_service,
                self._target_service,
            )
