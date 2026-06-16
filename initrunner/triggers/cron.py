"""Cron-based trigger using croniter."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from zoneinfo import ZoneInfo

from croniter import croniter

from initrunner.agent.schema.triggers import CronTriggerConfig
from initrunner.triggers.base import TriggerBase, TriggerEvent


class CronTrigger(TriggerBase):
    """Fires on a cron schedule."""

    def __init__(self, config: CronTriggerConfig, callback: Callable[[TriggerEvent], None]) -> None:
        super().__init__(callback)
        self._config = config

    def _run(self) -> None:
        # Evaluate the schedule in the configured timezone (not always UTC), so
        # e.g. "0 9 * * *" with timezone America/New_York fires at 09:00 local.
        tz = ZoneInfo(self._config.timezone)
        cron = croniter(self._config.schedule, datetime.now(tz))
        while not self._stop_event.is_set():
            next_time = cron.get_next(datetime)
            now = datetime.now(tz)
            wait_seconds = (next_time - now).total_seconds()
            if wait_seconds > 0:
                # Sleep in 1s increments to allow clean shutdown
                while wait_seconds > 0 and not self._stop_event.is_set():
                    self._stop_event.wait(min(wait_seconds, 1.0))
                    wait_seconds = (next_time - datetime.now(tz)).total_seconds()
            if self._stop_event.is_set():
                break
            event = TriggerEvent(
                trigger_type="cron",
                prompt=self._config.prompt,
                metadata={"schedule": self._config.schedule},
            )
            self._callback(event)
