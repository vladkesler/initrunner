"""Thread-safe token budget tracking for daemon mode."""

from __future__ import annotations

import threading
from datetime import UTC, datetime


class DaemonTokenTracker:
    """Thread-safe token budget tracker for daemon mode."""

    # Tentative reservation to prevent two concurrent triggers from both
    # passing the budget check before either records actual usage.
    _RESERVATION = 1

    def __init__(self, lifetime_budget: int | None, daily_budget: int | None) -> None:
        self.lifetime_budget = lifetime_budget
        self.daily_budget = daily_budget
        self._lock = threading.Lock()
        self.total_consumed = 0
        self.daily_consumed = 0
        self.last_reset_date = datetime.now(UTC).date()
        self._pending_reservations = 0

    def check_before_run(self) -> tuple[bool, str | None]:
        """Atomically check budget and reserve a token. Returns (is_allowed, reason)."""
        with self._lock:
            today = datetime.now(UTC).date()
            if today > self.last_reset_date:
                self.daily_consumed = 0
                self.last_reset_date = today
            if self.lifetime_budget and self.total_consumed >= self.lifetime_budget:
                return False, (
                    f"Lifetime budget exhausted ({self.total_consumed:,}/{self.lifetime_budget:,})"
                )
            if self.daily_budget and self.daily_consumed >= self.daily_budget:
                return False, (
                    f"Daily budget exhausted ({self.daily_consumed:,}/{self.daily_budget:,})"
                )
            # Reserve a token to prevent concurrent over-budget runs
            self.total_consumed += self._RESERVATION
            self.daily_consumed += self._RESERVATION
            self._pending_reservations += 1
            return True, None

    def record_usage(self, tokens: int) -> None:
        """Record actual token usage, adjusting for any tentative reservation."""
        with self._lock:
            if self._pending_reservations > 0:
                self._pending_reservations -= 1
                actual = tokens - self._RESERVATION
            else:
                actual = tokens
            self.total_consumed += actual
            self.daily_consumed += actual
