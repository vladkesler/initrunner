"""Tests for budget state persistence and BudgetSnapshot."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from initrunner.runner.budget import BudgetSnapshot, DaemonTokenTracker, _year_week

# ---------------------------------------------------------------------------
# BudgetSnapshot
# ---------------------------------------------------------------------------


class TestBudgetSnapshot:
    def test_round_trip(self):
        snap = BudgetSnapshot(
            total_consumed=100,
            daily_consumed=50,
            daily_cost_consumed=1.23,
            weekly_cost_consumed=4.56,
            last_reset_date="2026-04-12",
            last_weekly_reset="2026-W15",
        )
        d = snap.to_dict()
        restored = BudgetSnapshot.from_dict(d)
        assert restored == snap

    def test_with_resets_stale_daily(self):
        snap = BudgetSnapshot(
            total_consumed=100,
            daily_consumed=50,
            daily_cost_consumed=1.0,
            weekly_cost_consumed=2.0,
            last_reset_date="2020-01-01",
            last_weekly_reset=_year_week(datetime.now(ZoneInfo("UTC"))),
        )
        clean = snap.with_resets("UTC")
        assert clean.daily_consumed == 0
        assert clean.daily_cost_consumed == 0.0
        # Weekly should NOT reset (same week)
        assert clean.weekly_cost_consumed == 2.0
        # Total is preserved
        assert clean.total_consumed == 100

    def test_with_resets_stale_weekly(self):
        snap = BudgetSnapshot(
            total_consumed=200,
            daily_consumed=0,
            daily_cost_consumed=0.0,
            weekly_cost_consumed=5.0,
            last_reset_date=datetime.now(ZoneInfo("UTC")).date().isoformat(),
            last_weekly_reset="2020-W01",
        )
        clean = snap.with_resets("UTC")
        assert clean.weekly_cost_consumed == 0.0

    def test_with_resets_year_boundary(self):
        """Week 52 of one year != week 1 of the next."""
        snap = BudgetSnapshot(
            total_consumed=0,
            daily_consumed=0,
            daily_cost_consumed=0.0,
            weekly_cost_consumed=10.0,
            last_reset_date=datetime.now(ZoneInfo("UTC")).date().isoformat(),
            last_weekly_reset="2025-W52",
        )
        # Current week is definitely not 2025-W52
        clean = snap.with_resets("UTC")
        assert clean.weekly_cost_consumed == 0.0

    def test_with_resets_current_no_change(self):
        now = datetime.now(ZoneInfo("UTC"))
        snap = BudgetSnapshot(
            total_consumed=100,
            daily_consumed=50,
            daily_cost_consumed=1.0,
            weekly_cost_consumed=2.0,
            last_reset_date=now.date().isoformat(),
            last_weekly_reset=_year_week(now),
        )
        clean = snap.with_resets("UTC")
        assert clean == snap

    def test_to_progress_unconfigured(self):
        """Returns None for unconfigured budgets."""

        class FakeGuardrails:
            daemon_token_budget = None
            daemon_daily_token_budget = None
            daemon_daily_cost_budget = None
            daemon_weekly_cost_budget = None

        snap = BudgetSnapshot(
            total_consumed=0,
            daily_consumed=0,
            daily_cost_consumed=0.0,
            weekly_cost_consumed=0.0,
            last_reset_date="2026-04-12",
            last_weekly_reset="2026-W15",
        )
        progress = snap.to_progress(FakeGuardrails())
        assert progress["daily_tokens"] is None
        assert progress["daily_cost"] is None
        assert progress["weekly_cost"] is None
        assert progress["lifetime_tokens"] is None

    def test_to_progress_warning_levels(self):
        class FakeGuardrails:
            daemon_token_budget = None
            daemon_daily_token_budget = None
            daemon_daily_cost_budget = 10.0
            daemon_weekly_cost_budget = 50.0

        snap = BudgetSnapshot(
            total_consumed=0,
            daily_consumed=0,
            daily_cost_consumed=8.5,  # 85% -> warning_80
            weekly_cost_consumed=48.0,  # 96% -> warning_95
            last_reset_date="2026-04-12",
            last_weekly_reset="2026-W15",
        )
        progress = snap.to_progress(FakeGuardrails())
        assert progress["daily_cost"]["warning_level"] == "warning_80"
        assert progress["weekly_cost"]["warning_level"] == "warning_95"

    def test_to_progress_exhausted(self):
        class FakeGuardrails:
            daemon_token_budget = None
            daemon_daily_token_budget = 100
            daemon_daily_cost_budget = None
            daemon_weekly_cost_budget = None

        snap = BudgetSnapshot(
            total_consumed=0,
            daily_consumed=150,
            daily_cost_consumed=0.0,
            weekly_cost_consumed=0.0,
            last_reset_date="2026-04-12",
            last_weekly_reset="2026-W15",
        )
        progress = snap.to_progress(FakeGuardrails())
        assert progress["daily_tokens"]["warning_level"] == "exhausted"
        assert progress["daily_tokens"]["percent"] == 100.0

    def test_with_resets_timezone_aware(self):
        """Reset uses the configured timezone, not UTC."""
        # Use a timezone that's ahead of UTC so "today" might differ
        snap = BudgetSnapshot(
            total_consumed=100,
            daily_consumed=50,
            daily_cost_consumed=1.0,
            weekly_cost_consumed=2.0,
            last_reset_date="2020-01-01",
            last_weekly_reset="2020-W01",
        )
        clean = snap.with_resets("America/New_York")
        assert clean.daily_consumed == 0
        assert clean.weekly_cost_consumed == 0.0


# ---------------------------------------------------------------------------
# DaemonTokenTracker: snapshot / restore / update_limits
# ---------------------------------------------------------------------------


class TestTrackerSnapshotRestore:
    def test_snapshot_returns_current_state(self):
        tracker = DaemonTokenTracker(lifetime_budget=1000, daily_budget=500)
        tracker.record_usage(100, 50)
        snap = tracker.snapshot()
        assert snap.total_consumed == 150
        assert snap.daily_consumed == 150

    def test_restore_applies_resets(self):
        tracker = DaemonTokenTracker(lifetime_budget=1000, daily_budget=500)
        stale = BudgetSnapshot(
            total_consumed=300,
            daily_consumed=200,
            daily_cost_consumed=1.5,
            weekly_cost_consumed=3.0,
            last_reset_date="2020-01-01",
            last_weekly_reset="2020-W01",
        )
        tracker.restore(stale)
        assert tracker.total_consumed == 300
        assert tracker.daily_consumed == 0  # reset due to stale date
        assert tracker.daily_cost_consumed == 0.0

    def test_restore_failure_starts_fresh(self):
        tracker = DaemonTokenTracker(lifetime_budget=1000, daily_budget=500)
        tracker.record_usage(100, 50)
        # Simulate restore failure via invalid snapshot causing an exception
        bad = BudgetSnapshot(
            total_consumed=0,
            daily_consumed=0,
            daily_cost_consumed=0.0,
            weekly_cost_consumed=0.0,
            last_reset_date="2026-04-12",
            last_weekly_reset="2026-W15",
        )
        with patch(
            "initrunner.runner.budget.BudgetSnapshot.with_resets",
            side_effect=RuntimeError("boom"),
        ):
            tracker.restore(bad)
        # Should still have prior state (restore failed, kept existing)
        assert tracker.total_consumed == 150

    def test_update_limits_preserves_counters(self):
        tracker = DaemonTokenTracker(
            lifetime_budget=1000,
            daily_budget=500,
            daily_cost_budget=10.0,
        )
        mock_cost = {"total_cost_usd": 1.0}
        with patch("initrunner.pricing.estimate_cost", return_value=mock_cost):
            tracker.record_usage(100, 50)

        tracker.update_limits(
            lifetime_budget=2000,
            daily_budget=1000,
            daily_cost_budget=20.0,
            weekly_cost_budget=None,
            timezone="America/Chicago",
        )
        assert tracker.lifetime_budget == 2000
        assert tracker.daily_budget == 1000
        assert tracker.total_consumed == 150  # preserved
        assert tracker.daily_cost_consumed == 1.0  # preserved

    def test_update_limits_clears_warnings(self):
        tracker = DaemonTokenTracker(
            lifetime_budget=None,
            daily_budget=None,
            daily_cost_budget=1.0,
        )
        tracker._warned["daily_cost"].add(80)
        tracker.update_limits(
            lifetime_budget=None,
            daily_budget=None,
            daily_cost_budget=2.0,
        )
        assert len(tracker._warned["daily_cost"]) == 0


# ---------------------------------------------------------------------------
# Tracker: 95% warnings
# ---------------------------------------------------------------------------


class TestTrackerWarnings:
    def test_80_and_95_fire_separately(self):
        tracker = DaemonTokenTracker(
            lifetime_budget=None,
            daily_budget=None,
            daily_cost_budget=10.0,
            model="gpt-4o",
            provider="openai",
        )
        mock_cost = {"total_cost_usd": 8.5}
        with patch("initrunner.pricing.estimate_cost", return_value=mock_cost):
            tracker.record_usage(100, 50)
        assert 80 in tracker._warned["daily_cost"]
        assert 95 not in tracker._warned["daily_cost"]

        mock_cost2 = {"total_cost_usd": 1.5}
        with patch("initrunner.pricing.estimate_cost", return_value=mock_cost2):
            tracker.record_usage(100, 50)
        assert 95 in tracker._warned["daily_cost"]

    def test_warnings_dont_repeat(self):
        tracker = DaemonTokenTracker(
            lifetime_budget=None,
            daily_budget=None,
            daily_cost_budget=10.0,
            model="gpt-4o",
            provider="openai",
        )
        # Push past 95% in one go
        mock_cost = {"total_cost_usd": 9.6}
        with patch("initrunner.pricing.estimate_cost", return_value=mock_cost):
            tracker.record_usage(100, 50)
        assert 80 in tracker._warned["daily_cost"]
        assert 95 in tracker._warned["daily_cost"]

        # Record again -- should not re-add (set doesn't change)
        with patch("initrunner.pricing.estimate_cost", return_value={"total_cost_usd": 0.1}):
            tracker.record_usage(10, 5)
        assert tracker._warned["daily_cost"] == {80, 95}

    def test_daily_reset_clears_warnings(self):
        tracker = DaemonTokenTracker(
            lifetime_budget=None,
            daily_budget=None,
            daily_cost_budget=10.0,
        )
        tracker._warned["daily_cost"].add(80)
        tracker._warned["daily_cost"].add(95)

        # Simulate day change
        tracker.last_reset_date = "2020-01-01"
        tracker.check_before_run()
        assert len(tracker._warned["daily_cost"]) == 0


# ---------------------------------------------------------------------------
# Tracker: timezone
# ---------------------------------------------------------------------------


class TestTrackerTimezone:
    def test_timezone_param_accepted(self):
        tracker = DaemonTokenTracker(
            lifetime_budget=None,
            daily_budget=None,
            timezone="America/New_York",
        )
        assert str(tracker._tz) == "America/New_York"

    def test_default_timezone_is_utc(self):
        tracker = DaemonTokenTracker(lifetime_budget=None, daily_budget=None)
        assert str(tracker._tz) == "UTC"


# ---------------------------------------------------------------------------
# AuditLogger: budget state persistence
# ---------------------------------------------------------------------------


class TestAuditLoggerBudgetState:
    @pytest.fixture
    def audit_logger(self, tmp_path: Path):
        from initrunner.audit.logger import AuditLogger

        return AuditLogger(tmp_path / "test_audit.db")

    def test_save_load_round_trip(self, audit_logger):
        state = {
            "total_consumed": 1000,
            "daily_consumed": 200,
            "daily_cost_consumed": 1.5,
            "weekly_cost_consumed": 3.0,
            "last_reset_date": "2026-04-12",
            "last_weekly_reset": "2026-W15",
        }
        audit_logger.save_budget_state("test-agent", state)
        loaded = audit_logger.load_budget_state("test-agent")
        assert loaded is not None
        assert loaded["total_consumed"] == 1000
        assert loaded["daily_consumed"] == 200
        assert loaded["daily_cost_consumed"] == 1.5
        assert loaded["weekly_cost_consumed"] == 3.0
        assert loaded["last_reset_date"] == "2026-04-12"
        assert loaded["last_weekly_reset"] == "2026-W15"

    def test_upsert_replaces(self, audit_logger):
        state1 = {
            "total_consumed": 100,
            "daily_consumed": 50,
            "daily_cost_consumed": 0.5,
            "weekly_cost_consumed": 1.0,
            "last_reset_date": "2026-04-12",
            "last_weekly_reset": "2026-W15",
        }
        audit_logger.save_budget_state("test-agent", state1)

        state2 = {
            "total_consumed": 200,
            "daily_consumed": 75,
            "daily_cost_consumed": 1.0,
            "weekly_cost_consumed": 2.0,
            "last_reset_date": "2026-04-12",
            "last_weekly_reset": "2026-W15",
        }
        audit_logger.save_budget_state("test-agent", state2)

        loaded = audit_logger.load_budget_state("test-agent")
        assert loaded is not None
        assert loaded["total_consumed"] == 200

    def test_load_missing_returns_none(self, audit_logger):
        assert audit_logger.load_budget_state("nonexistent") is None

    def test_table_creation_idempotent(self, tmp_path: Path):
        from initrunner.audit.logger import AuditLogger

        # Create twice
        al1 = AuditLogger(tmp_path / "idem.db")
        al1.close()
        al2 = AuditLogger(tmp_path / "idem.db")
        al2.close()  # Should not raise


# ---------------------------------------------------------------------------
# Guardrails schema: budget_timezone
# ---------------------------------------------------------------------------


class TestGuardrailsBudgetTimezone:
    def test_default_is_utc(self):
        from initrunner.agent.schema.guardrails import Guardrails

        g = Guardrails()
        assert g.budget_timezone == "UTC"

    def test_valid_timezone(self):
        from initrunner.agent.schema.guardrails import Guardrails

        g = Guardrails(budget_timezone="America/New_York")
        assert g.budget_timezone == "America/New_York"

    def test_invalid_timezone_rejected(self):
        from pydantic import ValidationError

        from initrunner.agent.schema.guardrails import Guardrails

        with pytest.raises(ValidationError, match="Invalid IANA timezone"):
            Guardrails(budget_timezone="FakeZone/Nowhere")
