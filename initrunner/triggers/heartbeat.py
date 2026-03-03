"""Heartbeat trigger: reads a markdown checklist on a fixed interval."""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from datetime import datetime
from zoneinfo import ZoneInfo

from initrunner.agent.schema.triggers import HeartbeatTriggerConfig
from initrunner.triggers.base import TriggerBase, TriggerEvent

_logger = logging.getLogger(__name__)

_MAX_FILE_SIZE = 64 * 1024  # 64KB


class HeartbeatTrigger(TriggerBase):
    """Fires on a fixed interval, reading a checklist file each time."""

    def __init__(
        self, config: HeartbeatTriggerConfig, callback: Callable[[TriggerEvent], None]
    ) -> None:
        super().__init__(callback)
        self._config = config

    def _run(self) -> None:
        interval = self._config.interval_seconds

        # Wait for the first full interval before firing
        remaining = float(interval)
        while remaining > 0 and not self._stop_event.is_set():
            self._stop_event.wait(min(remaining, 1.0))
            remaining -= 1.0

        while not self._stop_event.is_set():
            if self._is_active(_now(self._config.timezone)):
                content = self._read_checklist()
                if content is not None:
                    open_count = _count_open_items(content)
                    if open_count > 0:
                        prompt = _build_prompt(self._config.prompt_prefix, content)
                        event = TriggerEvent(
                            trigger_type="heartbeat",
                            prompt=prompt,
                            metadata={
                                "file": self._config.file,
                                "item_count": str(open_count),
                                "interval_seconds": str(self._config.interval_seconds),
                            },
                        )
                        self._callback(event)

            # Sleep for next interval in 1s increments
            remaining = float(interval)
            while remaining > 0 and not self._stop_event.is_set():
                self._stop_event.wait(min(remaining, 1.0))
                remaining -= 1.0

    def _is_active(self, now: datetime) -> bool:
        """Check if the current hour falls within active_hours."""
        hours = self._config.active_hours
        if hours is None:
            return True
        start, end = hours
        hour = now.hour
        if start < end:
            # Normal window: e.g. [9, 17] means 9 <= hour < 17
            return start <= hour < end
        else:
            # Midnight-spanning: e.g. [22, 6] means hour >= 22 or hour < 6
            return hour >= start or hour < end

    def _read_checklist(self) -> str | None:
        """Read the checklist file, capping at 64KB."""
        try:
            with open(self._config.file) as f:
                content = f.read(_MAX_FILE_SIZE + 1)
            if len(content) > _MAX_FILE_SIZE:
                content = content[:_MAX_FILE_SIZE] + "\n[truncated]"
            return content
        except Exception:
            _logger.warning(
                "Failed to read heartbeat checklist %s",
                self._config.file,
                exc_info=True,
            )
            return None


def _now(timezone: str) -> datetime:
    """Return the current time in the given timezone."""
    return datetime.now(ZoneInfo(timezone))


def _count_open_items(content: str) -> int:
    """Count unchecked markdown checklist items (``- [ ]``)."""
    return len(re.findall(r"^- \[ \]", content, re.MULTILINE))


def _build_prompt(prefix: str, content: str) -> str:
    """Compose the prompt from prefix and checklist content."""
    return prefix + "\n\n" + content
