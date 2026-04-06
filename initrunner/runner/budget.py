"""Thread-safe token and cost budget tracking for daemon mode."""

from __future__ import annotations

import logging
import threading
from datetime import UTC, datetime

_logger = logging.getLogger(__name__)


class DaemonTokenTracker:
    """Thread-safe token and USD cost budget tracker for daemon mode."""

    # Tentative reservation to prevent two concurrent triggers from both
    # passing the budget check before either records actual usage.
    _RESERVATION = 1

    def __init__(
        self,
        lifetime_budget: int | None,
        daily_budget: int | None,
        *,
        daily_cost_budget: float | None = None,
        weekly_cost_budget: float | None = None,
        model: str = "",
        provider: str = "",
    ) -> None:
        self.lifetime_budget = lifetime_budget
        self.daily_budget = daily_budget
        self.daily_cost_budget = daily_cost_budget
        self.weekly_cost_budget = weekly_cost_budget
        self._model = model
        self._provider = provider

        self._lock = threading.Lock()
        self.total_consumed = 0
        self.daily_consumed = 0
        self.last_reset_date = datetime.now(UTC).date()

        # Cost tracking
        self.daily_cost_consumed: float = 0.0
        self.weekly_cost_consumed: float = 0.0
        self._last_weekly_reset_week = datetime.now(UTC).isocalendar()[1]

        self._pending_reservations = 0
        self._cost_warning_logged = False

    def check_before_run(self) -> tuple[bool, str | None]:
        """Atomically check budget and reserve a token. Returns (is_allowed, reason)."""
        with self._lock:
            today = datetime.now(UTC)
            today_date = today.date()
            today_week = today.isocalendar()[1]

            # Daily reset
            if today_date > self.last_reset_date:
                self.daily_consumed = 0
                self.daily_cost_consumed = 0.0
                self.last_reset_date = today_date

            # Weekly reset
            if today_week != self._last_weekly_reset_week:
                self.weekly_cost_consumed = 0.0
                self._last_weekly_reset_week = today_week

            # Token budget checks
            if self.lifetime_budget and self.total_consumed >= self.lifetime_budget:
                return False, (
                    f"Lifetime budget exhausted ({self.total_consumed:,}/{self.lifetime_budget:,})"
                )
            if self.daily_budget and self.daily_consumed >= self.daily_budget:
                return False, (
                    f"Daily budget exhausted ({self.daily_consumed:,}/{self.daily_budget:,})"
                )

            # Cost budget checks
            if self.daily_cost_budget and self.daily_cost_consumed >= self.daily_cost_budget:
                used = f"${self.daily_cost_consumed:.4f}"
                cap = f"${self.daily_cost_budget:.4f}"
                return False, f"Daily cost budget exhausted ({used}/{cap})"
            if self.weekly_cost_budget and self.weekly_cost_consumed >= self.weekly_cost_budget:
                used = f"${self.weekly_cost_consumed:.4f}"
                cap = f"${self.weekly_cost_budget:.4f}"
                return False, f"Weekly cost budget exhausted ({used}/{cap})"

            # Reserve a token to prevent concurrent over-budget runs
            self.total_consumed += self._RESERVATION
            self.daily_consumed += self._RESERVATION
            self._pending_reservations += 1
            return True, None

    def record_usage(self, tokens_in: int, tokens_out: int) -> None:
        """Record actual token and cost usage, adjusting for any tentative reservation."""
        total = tokens_in + tokens_out
        with self._lock:
            if self._pending_reservations > 0:
                self._pending_reservations -= 1
                actual = total - self._RESERVATION
            else:
                actual = total
            self.total_consumed += actual
            self.daily_consumed += actual

            # Cost accumulation
            if self.daily_cost_budget or self.weekly_cost_budget:
                cost = self._estimate_cost(tokens_in, tokens_out)
                if cost is not None:
                    self.daily_cost_consumed += cost
                    self.weekly_cost_consumed += cost
                    self._check_cost_warnings()

    def _estimate_cost(self, tokens_in: int, tokens_out: int) -> float | None:
        """Estimate USD cost for a single run."""
        from initrunner.pricing import estimate_cost

        result = estimate_cost(tokens_in, tokens_out, self._model, self._provider)
        if result is None:
            if not self._cost_warning_logged:
                _logger.warning(
                    "Cost estimation unavailable for %s/%s; cost budget tracking degraded",
                    self._provider,
                    self._model,
                )
                self._cost_warning_logged = True
            return None
        return result["total_cost_usd"]

    def _check_cost_warnings(self) -> None:
        """Log warnings at 80% of cost budgets."""
        if self.daily_cost_budget and self.daily_cost_consumed >= self.daily_cost_budget * 0.8:
            pct = int(self.daily_cost_consumed / self.daily_cost_budget * 100)
            _logger.warning(
                "Daily cost budget %d%% consumed ($%.4f/$%.4f)",
                pct,
                self.daily_cost_consumed,
                self.daily_cost_budget,
            )
        if self.weekly_cost_budget and self.weekly_cost_consumed >= self.weekly_cost_budget * 0.8:
            pct = int(self.weekly_cost_consumed / self.weekly_cost_budget * 100)
            _logger.warning(
                "Weekly cost budget %d%% consumed ($%.4f/$%.4f)",
                pct,
                self.weekly_cost_consumed,
                self.weekly_cost_budget,
            )
