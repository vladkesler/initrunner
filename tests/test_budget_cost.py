"""Tests for USD cost budget enforcement in DaemonTokenTracker."""

from __future__ import annotations

from unittest.mock import patch

from initrunner.runner.budget import DaemonTokenTracker


class TestDaemonTokenTrackerCostBudget:
    def test_no_cost_budget_backward_compat(self) -> None:
        """Tracker works without cost budgets (token-only mode)."""
        tracker = DaemonTokenTracker(lifetime_budget=1000, daily_budget=500)
        allowed, reason = tracker.check_before_run()
        assert allowed is True
        tracker.record_usage(100, 50)
        assert tracker.total_consumed == 150
        assert tracker.daily_consumed == 150

    def test_daily_cost_budget_enforcement(self) -> None:
        """Daily cost budget blocks runs when exceeded."""
        tracker = DaemonTokenTracker(
            lifetime_budget=None,
            daily_budget=None,
            daily_cost_budget=0.01,
            model="gpt-4o",
            provider="openai",
        )

        # Mock estimate_cost to return predictable values
        mock_cost = {"input_cost_usd": 0.005, "output_cost_usd": 0.003, "total_cost_usd": 0.008}
        with patch("initrunner.pricing.estimate_cost", return_value=mock_cost):
            tracker.record_usage(100, 50)
            assert tracker.daily_cost_consumed == 0.008

            # Second run pushes over budget
            tracker.record_usage(100, 50)
            assert tracker.daily_cost_consumed == 0.016

        # Now check should fail
        allowed, reason = tracker.check_before_run()
        assert allowed is False
        assert "cost budget" in reason.lower()

    def test_weekly_cost_budget_enforcement(self) -> None:
        """Weekly cost budget blocks runs when exceeded."""
        tracker = DaemonTokenTracker(
            lifetime_budget=None,
            daily_budget=None,
            weekly_cost_budget=0.01,
            model="gpt-4o",
            provider="openai",
        )

        mock_cost = {"input_cost_usd": 0.005, "output_cost_usd": 0.006, "total_cost_usd": 0.011}
        with patch("initrunner.pricing.estimate_cost", return_value=mock_cost):
            tracker.record_usage(100, 50)

        allowed, reason = tracker.check_before_run()
        assert allowed is False
        assert "weekly" in reason.lower()

    def test_cost_budget_daily_reset(self) -> None:
        """Daily cost resets when date changes."""
        from datetime import date

        tracker = DaemonTokenTracker(
            lifetime_budget=None,
            daily_budget=None,
            daily_cost_budget=0.01,
            model="gpt-4o",
            provider="openai",
        )

        mock_cost = {"input_cost_usd": 0.005, "output_cost_usd": 0.006, "total_cost_usd": 0.011}
        with patch("initrunner.pricing.estimate_cost", return_value=mock_cost):
            tracker.record_usage(100, 50)

        assert tracker.daily_cost_consumed == 0.011

        # Simulate date change
        from datetime import timedelta

        tracker.last_reset_date = date.today() - timedelta(days=1)

        # check_before_run should reset daily counters
        allowed, reason = tracker.check_before_run()
        assert allowed is True
        assert tracker.daily_cost_consumed == 0.0

    def test_unpriceable_model_degrades_gracefully(self) -> None:
        """Cost tracking degrades gracefully when pricing is unavailable."""
        tracker = DaemonTokenTracker(
            lifetime_budget=None,
            daily_budget=None,
            daily_cost_budget=0.01,
            model="custom-model",
            provider="custom-provider",
        )

        with patch("initrunner.pricing.estimate_cost", return_value=None):
            tracker.record_usage(100, 50)

        # Cost should remain 0 (pricing unavailable)
        assert tracker.daily_cost_consumed == 0.0
        # Token tracking still works
        assert tracker.total_consumed == 150

    def test_token_and_cost_budgets_combined(self) -> None:
        """Both token and cost budgets are enforced independently."""
        tracker = DaemonTokenTracker(
            lifetime_budget=None,
            daily_budget=200,  # Will be exceeded
            daily_cost_budget=100.0,  # Won't be exceeded
            model="gpt-4o",
            provider="openai",
        )

        mock_cost = {"input_cost_usd": 0.001, "output_cost_usd": 0.001, "total_cost_usd": 0.002}
        with patch("initrunner.pricing.estimate_cost", return_value=mock_cost):
            tracker.record_usage(100, 50)
            tracker.record_usage(100, 50)

        # Token budget exceeded, cost budget not
        allowed, reason = tracker.check_before_run()
        assert allowed is False
        assert "Daily budget exhausted" in reason

    def test_record_usage_new_signature(self) -> None:
        """record_usage takes tokens_in and tokens_out."""
        tracker = DaemonTokenTracker(lifetime_budget=None, daily_budget=None)
        tracker.record_usage(100, 50)
        assert tracker.total_consumed == 150

    def test_reservation_mechanism_preserved(self) -> None:
        """Tentative reservation is correctly adjusted."""
        tracker = DaemonTokenTracker(lifetime_budget=None, daily_budget=None)
        # check_before_run adds a reservation
        allowed, _ = tracker.check_before_run()
        assert allowed
        assert tracker.total_consumed == 1
        assert tracker._pending_reservations == 1

        # record_usage adjusts for the reservation
        tracker.record_usage(100, 50)  # total = 150
        assert tracker.total_consumed == 150  # 1 + (150 - 1)
        assert tracker._pending_reservations == 0


class TestGuardrailsCostFields:
    def test_guardrails_accepts_cost_budgets(self) -> None:
        """Guardrails schema accepts the new cost budget fields."""
        from initrunner.agent.schema.guardrails import Guardrails

        g = Guardrails(daemon_daily_cost_budget=1.50, daemon_weekly_cost_budget=10.0)
        assert g.daemon_daily_cost_budget == 1.50
        assert g.daemon_weekly_cost_budget == 10.0

    def test_guardrails_defaults_none(self) -> None:
        from initrunner.agent.schema.guardrails import Guardrails

        g = Guardrails()
        assert g.daemon_daily_cost_budget is None
        assert g.daemon_weekly_cost_budget is None

    def test_guardrails_rejects_zero(self) -> None:
        from pydantic import ValidationError

        from initrunner.agent.schema.guardrails import Guardrails

        with __import__("pytest").raises(ValidationError):
            Guardrails(daemon_daily_cost_budget=0)

    def test_guardrails_rejects_negative(self) -> None:
        from pydantic import ValidationError

        from initrunner.agent.schema.guardrails import Guardrails

        with __import__("pytest").raises(ValidationError):
            Guardrails(daemon_daily_cost_budget=-1.0)
