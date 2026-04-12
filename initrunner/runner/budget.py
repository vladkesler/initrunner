"""Thread-safe token and cost budget tracking for daemon mode."""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

_logger = logging.getLogger(__name__)


def _year_week(dt: datetime) -> str:
    """Return ISO year-week string like ``'2026-W15'``."""
    cal = dt.isocalendar()
    return f"{cal[0]}-W{cal[1]:02d}"


# ---------------------------------------------------------------------------
# Snapshot -- pure-data boundary for persistence and gauge computation
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BudgetSnapshot:
    """Immutable point-in-time capture of budget counters."""

    total_consumed: int
    daily_consumed: int
    daily_cost_consumed: float
    weekly_cost_consumed: float
    last_reset_date: str  # "2026-04-12"
    last_weekly_reset: str  # "2026-W15"

    # -- serialisation -------------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "total_consumed": self.total_consumed,
            "daily_consumed": self.daily_consumed,
            "daily_cost_consumed": self.daily_cost_consumed,
            "weekly_cost_consumed": self.weekly_cost_consumed,
            "last_reset_date": self.last_reset_date,
            "last_weekly_reset": self.last_weekly_reset,
        }

    @classmethod
    def from_dict(cls, d: dict) -> BudgetSnapshot:
        return cls(
            total_consumed=int(d["total_consumed"]),
            daily_consumed=int(d["daily_consumed"]),
            daily_cost_consumed=float(d["daily_cost_consumed"]),
            weekly_cost_consumed=float(d["weekly_cost_consumed"]),
            last_reset_date=str(d["last_reset_date"]),
            last_weekly_reset=str(d["last_weekly_reset"]),
        )

    # -- resets --------------------------------------------------------------

    def with_resets(self, tz: str = "UTC") -> BudgetSnapshot:
        """Return a copy with date/week boundary resets applied."""
        now = datetime.now(ZoneInfo(tz))
        today_str = now.date().isoformat()
        current_week = _year_week(now)

        daily_consumed = self.daily_consumed
        daily_cost = self.daily_cost_consumed
        reset_date = self.last_reset_date
        weekly_cost = self.weekly_cost_consumed
        weekly_reset = self.last_weekly_reset

        if today_str > reset_date:
            daily_consumed = 0
            daily_cost = 0.0
            reset_date = today_str

        if current_week != weekly_reset:
            weekly_cost = 0.0
            weekly_reset = current_week

        return BudgetSnapshot(
            total_consumed=self.total_consumed,
            daily_consumed=daily_consumed,
            daily_cost_consumed=daily_cost,
            weekly_cost_consumed=weekly_cost,
            last_reset_date=reset_date,
            last_weekly_reset=weekly_reset,
        )

    # -- gauge computation ---------------------------------------------------

    def to_progress(self, guardrails: object) -> dict:
        """Compute budget gauges from snapshot + guardrails.

        Returns ``{"daily_tokens": gauge|None, ...}`` where each gauge is
        ``{"consumed", "limit", "percent", "warning_level"}``.
        """

        def _gauge(consumed: float, limit: float | None) -> dict | None:
            if limit is None:
                return None
            pct = min(100.0, round(consumed / limit * 100, 1)) if limit > 0 else 100.0
            if consumed >= limit:
                level = "exhausted"
            elif pct >= 95:
                level = "warning_95"
            elif pct >= 80:
                level = "warning_80"
            else:
                level = "ok"
            return {
                "consumed": consumed,
                "limit": limit,
                "percent": pct,
                "warning_level": level,
            }

        g = guardrails  # type: ignore[assignment]
        daily_tok = getattr(g, "daemon_daily_token_budget", None)
        daily_cost = getattr(g, "daemon_daily_cost_budget", None)
        weekly_cost = getattr(g, "daemon_weekly_cost_budget", None)
        lifetime = getattr(g, "daemon_token_budget", None)
        return {
            "daily_tokens": _gauge(self.daily_consumed, daily_tok),
            "daily_cost": _gauge(self.daily_cost_consumed, daily_cost),
            "weekly_cost": _gauge(self.weekly_cost_consumed, weekly_cost),
            "lifetime_tokens": _gauge(self.total_consumed, lifetime),
        }


# ---------------------------------------------------------------------------
# Live tracker
# ---------------------------------------------------------------------------


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
        timezone: str = "UTC",
    ) -> None:
        self.lifetime_budget = lifetime_budget
        self.daily_budget = daily_budget
        self.daily_cost_budget = daily_cost_budget
        self.weekly_cost_budget = weekly_cost_budget
        self._model = model
        self._provider = provider
        self._tz = ZoneInfo(timezone)

        self._lock = threading.Lock()
        now = datetime.now(self._tz)
        self.total_consumed = 0
        self.daily_consumed = 0
        self.last_reset_date = now.date().isoformat()

        # Cost tracking
        self.daily_cost_consumed: float = 0.0
        self.weekly_cost_consumed: float = 0.0
        self._last_weekly_reset = _year_week(now)

        self._pending_reservations = 0
        self._cost_pricing_warned = False
        # {budget_key: set of thresholds already warned}
        self._warned: dict[str, set[int]] = {"daily_cost": set(), "weekly_cost": set()}

    def check_before_run(self) -> tuple[bool, str | None]:
        """Atomically check budget and reserve a token. Returns (is_allowed, reason)."""
        with self._lock:
            now = datetime.now(self._tz)
            today_str = now.date().isoformat()
            current_week = _year_week(now)

            # Daily reset
            if today_str > self.last_reset_date:
                self.daily_consumed = 0
                self.daily_cost_consumed = 0.0
                self.last_reset_date = today_str
                self._warned["daily_cost"].clear()

            # Weekly reset
            if current_week != self._last_weekly_reset:
                self.weekly_cost_consumed = 0.0
                self._last_weekly_reset = current_week
                self._warned["weekly_cost"].clear()

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

    # -- snapshot / restore --------------------------------------------------

    def snapshot(self) -> BudgetSnapshot:
        """Return an immutable snapshot of current counters (thread-safe)."""
        with self._lock:
            return BudgetSnapshot(
                total_consumed=self.total_consumed,
                daily_consumed=self.daily_consumed,
                daily_cost_consumed=self.daily_cost_consumed,
                weekly_cost_consumed=self.weekly_cost_consumed,
                last_reset_date=self.last_reset_date,
                last_weekly_reset=self._last_weekly_reset,
            )

    def restore(self, snap: BudgetSnapshot) -> None:
        """Restore counters from a persisted snapshot, applying date resets."""
        try:
            tz_name = str(self._tz)
            clean = snap.with_resets(tz_name)
            with self._lock:
                self.total_consumed = clean.total_consumed
                self.daily_consumed = clean.daily_consumed
                self.daily_cost_consumed = clean.daily_cost_consumed
                self.weekly_cost_consumed = clean.weekly_cost_consumed
                self.last_reset_date = clean.last_reset_date
                self._last_weekly_reset = clean.last_weekly_reset
        except Exception:
            _logger.warning("Failed to restore budget state; starting fresh", exc_info=True)

    # -- hot-reload support --------------------------------------------------

    def update_limits(
        self,
        *,
        lifetime_budget: int | None,
        daily_budget: int | None,
        daily_cost_budget: float | None = None,
        weekly_cost_budget: float | None = None,
        timezone: str = "UTC",
    ) -> None:
        """Update budget limits and timezone, preserving accumulated counters."""
        with self._lock:
            self.lifetime_budget = lifetime_budget
            self.daily_budget = daily_budget
            self.daily_cost_budget = daily_cost_budget
            self.weekly_cost_budget = weekly_cost_budget
            self._tz = ZoneInfo(timezone)
            for s in self._warned.values():
                s.clear()

    # -- internals -----------------------------------------------------------

    def _estimate_cost(self, tokens_in: int, tokens_out: int) -> float | None:
        """Estimate USD cost for a single run."""
        from initrunner.pricing import estimate_cost

        result = estimate_cost(tokens_in, tokens_out, self._model, self._provider)
        if result is None:
            if not self._cost_pricing_warned:
                _logger.warning(
                    "Cost estimation unavailable for %s/%s; cost budget tracking degraded",
                    self._provider,
                    self._model,
                )
                self._cost_pricing_warned = True
            return None
        return result["total_cost_usd"]

    def _check_cost_warnings(self) -> None:
        """Log warnings at 80% and 95% of cost budgets."""
        for threshold in (80, 95):
            prefix = "CRITICAL: " if threshold == 95 else ""
            if self.daily_cost_budget and threshold not in self._warned["daily_cost"]:
                if self.daily_cost_consumed >= self.daily_cost_budget * threshold / 100:
                    pct = int(self.daily_cost_consumed / self.daily_cost_budget * 100)
                    _logger.warning(
                        "%sDaily cost budget %d%% consumed ($%.4f/$%.4f)",
                        prefix,
                        pct,
                        self.daily_cost_consumed,
                        self.daily_cost_budget,
                    )
                    self._warned["daily_cost"].add(threshold)
            if self.weekly_cost_budget and threshold not in self._warned["weekly_cost"]:
                if self.weekly_cost_consumed >= self.weekly_cost_budget * threshold / 100:
                    pct = int(self.weekly_cost_consumed / self.weekly_cost_budget * 100)
                    _logger.warning(
                        "%sWeekly cost budget %d%% consumed ($%.4f/$%.4f)",
                        prefix,
                        pct,
                        self.weekly_cost_consumed,
                        self.weekly_cost_budget,
                    )
                    self._warned["weekly_cost"].add(threshold)
