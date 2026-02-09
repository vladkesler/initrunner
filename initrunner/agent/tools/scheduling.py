"""Scheduling tools for daemon-mode agents: schedule_followup and schedule_followup_at.

These tools are NOT registered via @register_tool. They are injected at
runtime via extra_toolsets when a ScheduleQueue is available (daemon mode only).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from pydantic_ai.toolsets.function import FunctionToolset

from initrunner.agent.schema import AutonomyConfig
from initrunner.triggers.schedule_queue import ScheduleQueue

_logger = logging.getLogger(__name__)


def build_scheduling_toolset(
    config: AutonomyConfig,
    schedule_queue: ScheduleQueue,
) -> FunctionToolset:
    """Build scheduling tools: schedule_followup and schedule_followup_at."""
    max_per_run = config.max_scheduled_per_run
    max_delay = config.max_schedule_delay_seconds
    _run_schedule_count = {"count": 0}

    toolset = FunctionToolset()

    @toolset.tool
    def schedule_followup(prompt: str, delay_seconds: int) -> str:
        """Schedule a follow-up agent run after a delay.

        Args:
            prompt: The prompt for the follow-up run.
            delay_seconds: Seconds to wait before running (max 86400 = 24h).
        """
        if _run_schedule_count["count"] >= max_per_run:
            return f"Cannot schedule: per-run limit ({max_per_run}) reached."

        if delay_seconds < 1:
            return "Cannot schedule: delay must be at least 1 second."
        if delay_seconds > max_delay:
            return f"Cannot schedule: delay exceeds maximum ({max_delay}s)."

        try:
            task_id = schedule_queue.schedule(prompt, delay_seconds, run_id="daemon")
        except ValueError as e:
            return str(e)

        _run_schedule_count["count"] += 1
        return f"Scheduled follow-up in {delay_seconds}s (task_id={task_id})."

    @toolset.tool
    def schedule_followup_at(prompt: str, iso_datetime: str) -> str:
        """Schedule a follow-up agent run at a specific time.

        Args:
            prompt: The prompt for the follow-up run.
            iso_datetime: ISO 8601 datetime string (e.g. '2024-01-15T14:30:00Z').
        """
        if _run_schedule_count["count"] >= max_per_run:
            return f"Cannot schedule: per-run limit ({max_per_run}) reached."

        try:
            target = datetime.fromisoformat(iso_datetime)
        except ValueError:
            return f"Invalid ISO datetime: {iso_datetime}"

        if target.tzinfo is None:
            target = target.replace(tzinfo=UTC)

        now = datetime.now(UTC)
        delay = (target - now).total_seconds()

        if delay < 1:
            return "Cannot schedule: target time is in the past."
        if delay > max_delay:
            return f"Cannot schedule: delay exceeds maximum ({max_delay}s)."

        try:
            task_id = schedule_queue.schedule(prompt, delay, run_id="daemon")
        except ValueError as e:
            return str(e)

        _run_schedule_count["count"] += 1
        return f"Scheduled follow-up at {iso_datetime} (task_id={task_id})."

    return toolset
