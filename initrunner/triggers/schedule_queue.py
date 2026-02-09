"""In-memory schedule queue using threading.Timer for one-shot delayed runs."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field

from initrunner._ids import generate_id
from initrunner.triggers.base import TriggerEvent

_logger = logging.getLogger(__name__)


@dataclass
class _ScheduledTask:
    task_id: str
    prompt: str
    delay_seconds: float
    run_id: str
    timer: threading.Timer = field(repr=False)
    cancelled: bool = False


class ScheduleQueue:
    """Manages one-shot threading.Timer instances for scheduled agent runs.

    Pending tasks are in-memory and lost on daemon restart.
    """

    def __init__(
        self,
        on_trigger: Callable[[TriggerEvent], None],
        *,
        max_total: int = 50,
    ) -> None:
        self._on_trigger = on_trigger
        self._max_total = max_total
        self._lock = threading.Lock()
        self._pending: dict[str, _ScheduledTask] = {}
        _logger.warning("Scheduled tasks are in-memory only and will be lost on daemon restart.")

    def schedule(self, prompt: str, delay_seconds: float, run_id: str) -> str:
        """Schedule a one-shot run after *delay_seconds*.

        Returns the task ID.
        Raises ValueError if max_scheduled_total would be exceeded.
        """
        with self._lock:
            if len(self._pending) >= self._max_total:
                raise ValueError(
                    f"Maximum scheduled tasks ({self._max_total}) reached. Cannot schedule more."
                )

            task_id = generate_id()

            def _fire() -> None:
                with self._lock:
                    popped = self._pending.pop(task_id, None)
                if popped is None or popped.cancelled:
                    return
                event = TriggerEvent(
                    trigger_type="scheduled",
                    prompt=prompt,
                    metadata={
                        "scheduled_task_id": task_id,
                        "scheduled_by_run": run_id,
                    },
                )
                self._on_trigger(event)

            timer = threading.Timer(delay_seconds, _fire)
            timer.daemon = True
            task = _ScheduledTask(
                task_id=task_id,
                prompt=prompt,
                delay_seconds=delay_seconds,
                run_id=run_id,
                timer=timer,
            )
            self._pending[task_id] = task
            timer.start()
            _logger.info("Scheduled task %s in %.1fs (run_id=%s)", task_id, delay_seconds, run_id)
            return task_id

    def cancel_all(self) -> int:
        """Cancel all pending timers. Returns the count of cancelled tasks."""
        with self._lock:
            count = 0
            for task in self._pending.values():
                task.cancelled = True
                task.timer.cancel()
                count += 1
            self._pending.clear()
            return count

    @property
    def pending_count(self) -> int:
        with self._lock:
            return len(self._pending)
