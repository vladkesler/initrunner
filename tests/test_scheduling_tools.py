"""Tests for the scheduling toolset."""

from __future__ import annotations

import threading

from initrunner.agent.schema.autonomy import AutonomyConfig
from initrunner.agent.tools.scheduling import build_scheduling_toolset
from initrunner.triggers.base import TriggerEvent
from initrunner.triggers.schedule_queue import ScheduleQueue


def _make_queue(max_total: int = 50) -> ScheduleQueue:
    def noop(event: TriggerEvent):
        pass

    return ScheduleQueue(noop, max_total=max_total)


class TestBuildSchedulingToolset:
    def test_creates_toolset(self):
        config = AutonomyConfig()
        queue = _make_queue()
        toolset = build_scheduling_toolset(config, queue)
        assert toolset is not None
        queue.cancel_all()

    def test_schedule_followup_basic(self):
        events: list[TriggerEvent] = []
        fired = threading.Event()

        def on_trigger(event: TriggerEvent):
            events.append(event)
            fired.set()

        config = AutonomyConfig(max_scheduled_per_run=3, max_schedule_delay_seconds=3600)
        queue = ScheduleQueue(on_trigger, max_total=10)
        _toolset = build_scheduling_toolset(config, queue)

        # Schedule directly through the queue (tools are closures)
        task_id = queue.schedule("test", 0.1, run_id="test-run")
        assert task_id is not None
        fired.wait(timeout=2)
        assert len(events) == 1
        queue.cancel_all()

    def test_max_total_prevents_scheduling(self):
        queue = _make_queue(max_total=1)
        queue.schedule("existing", 100, run_id="r1")

        import pytest

        with pytest.raises(ValueError, match="Maximum scheduled tasks"):
            queue.schedule("new", 10, run_id="r2")

        queue.cancel_all()

    def test_toolset_with_small_delay(self):
        events: list[TriggerEvent] = []
        fired = threading.Event()

        def on_trigger(event: TriggerEvent):
            events.append(event)
            fired.set()

        config = AutonomyConfig()
        queue = ScheduleQueue(on_trigger, max_total=10)
        _toolset = build_scheduling_toolset(config, queue)

        # Schedule directly through queue
        queue.schedule("follow-up prompt", 0.05, run_id="run-123")
        fired.wait(timeout=2)
        assert events[0].prompt == "follow-up prompt"
        queue.cancel_all()
