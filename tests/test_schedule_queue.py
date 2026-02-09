"""Tests for the schedule queue."""

from __future__ import annotations

import threading
import time

from initrunner.triggers.base import TriggerEvent
from initrunner.triggers.schedule_queue import ScheduleQueue


class TestScheduleQueue:
    def test_schedule_fires_callback(self):
        events: list[TriggerEvent] = []
        fired = threading.Event()

        def on_trigger(event: TriggerEvent):
            events.append(event)
            fired.set()

        queue = ScheduleQueue(on_trigger, max_total=10)
        task_id = queue.schedule("test prompt", 0.1, run_id="run-1")

        assert task_id is not None
        assert len(task_id) == 12
        assert queue.pending_count == 1

        fired.wait(timeout=2)
        assert len(events) == 1
        assert events[0].trigger_type == "scheduled"
        assert events[0].prompt == "test prompt"
        assert events[0].metadata["scheduled_task_id"] == task_id
        assert events[0].metadata["scheduled_by_run"] == "run-1"
        assert queue.pending_count == 0

    def test_cancel_all(self):
        events: list[TriggerEvent] = []

        def on_trigger(event: TriggerEvent):
            events.append(event)

        queue = ScheduleQueue(on_trigger, max_total=10)
        queue.schedule("prompt 1", 10, run_id="r1")
        queue.schedule("prompt 2", 10, run_id="r2")
        assert queue.pending_count == 2

        cancelled = queue.cancel_all()
        assert cancelled == 2
        assert queue.pending_count == 0

        # Wait a bit to make sure nothing fires
        time.sleep(0.2)
        assert len(events) == 0

    def test_max_total_enforced(self):
        def on_trigger(event: TriggerEvent):
            pass

        queue = ScheduleQueue(on_trigger, max_total=2)
        queue.schedule("p1", 10, run_id="r1")
        queue.schedule("p2", 10, run_id="r2")

        import pytest

        with pytest.raises(ValueError, match="Maximum scheduled tasks"):
            queue.schedule("p3", 10, run_id="r3")

        queue.cancel_all()

    def test_pending_count_decrements_after_fire(self):
        fired = threading.Event()

        def on_trigger(event: TriggerEvent):
            fired.set()

        queue = ScheduleQueue(on_trigger, max_total=10)
        queue.schedule("prompt", 0.05, run_id="r1")
        assert queue.pending_count == 1

        fired.wait(timeout=2)
        # Give a tiny bit of time for cleanup
        time.sleep(0.05)
        assert queue.pending_count == 0

    def test_multiple_schedules_fire(self):
        events: list[TriggerEvent] = []
        all_fired = threading.Event()

        def on_trigger(event: TriggerEvent):
            events.append(event)
            if len(events) == 3:
                all_fired.set()

        queue = ScheduleQueue(on_trigger, max_total=10)
        queue.schedule("p1", 0.05, run_id="r1")
        queue.schedule("p2", 0.1, run_id="r2")
        queue.schedule("p3", 0.15, run_id="r3")

        all_fired.wait(timeout=3)
        assert len(events) == 3
        queue.cancel_all()
