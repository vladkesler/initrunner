"""Tests for per-run cumulative token budget in one-shot CLI mode."""

from __future__ import annotations

import textwrap
from unittest.mock import MagicMock, patch

import pytest

from initrunner.agent.delegation import InlineInvoker, reset_context
from initrunner.agent.schema.base import ApiVersion, Kind, ModelConfig, RoleMetadata
from initrunner.agent.schema.guardrails import Guardrails
from initrunner.agent.schema.role import AgentSpec, RoleDefinition
from initrunner.runner.budget import DaemonTokenTracker
from initrunner.runner.run_budget import (
    get_run_budget_tracker,
    make_single_shot_tracker,
    reset_run_budget_tracker,
    set_run_budget_tracker,
)


@pytest.fixture(autouse=True)
def _clean_context():
    reset_context()
    yield
    reset_context()


def _make_role(run_token_budget: int | None = None) -> RoleDefinition:
    return RoleDefinition(
        apiVersion=ApiVersion.V1,
        kind=Kind.AGENT,
        metadata=RoleMetadata(name="test-agent"),
        spec=AgentSpec(
            role="You are a test.",
            model=ModelConfig(provider="openai", name="gpt-5-mini"),
            guardrails=Guardrails(run_token_budget=run_token_budget),
        ),
    )


# ---------------------------------------------------------------------------
# Schema field
# ---------------------------------------------------------------------------


class TestSchemaField:
    def test_default_is_none(self):
        g = Guardrails()
        assert g.run_token_budget is None

    def test_positive_int_accepted(self):
        g = Guardrails(run_token_budget=10000)
        assert g.run_token_budget == 10000

    def test_zero_rejected(self):
        with pytest.raises(ValueError):
            Guardrails(run_token_budget=0)

    def test_negative_rejected(self):
        with pytest.raises(ValueError):
            Guardrails(run_token_budget=-1)


# ---------------------------------------------------------------------------
# make_single_shot_tracker
# ---------------------------------------------------------------------------


class TestMakeSingleShotTracker:
    def test_returns_none_when_unset(self):
        role = _make_role(run_token_budget=None)
        assert make_single_shot_tracker(role, override=None) is None

    def test_returns_tracker_from_role_field(self):
        role = _make_role(run_token_budget=5000)
        tracker = make_single_shot_tracker(role, override=None)
        assert tracker is not None
        assert tracker.lifetime_budget == 5000
        assert tracker.daily_budget is None

    def test_override_takes_precedence_over_field(self):
        role = _make_role(run_token_budget=5000)
        tracker = make_single_shot_tracker(role, override=100)
        assert tracker is not None
        assert tracker.lifetime_budget == 100

    def test_override_with_no_field_set(self):
        role = _make_role(run_token_budget=None)
        tracker = make_single_shot_tracker(role, override=2500)
        assert tracker is not None
        assert tracker.lifetime_budget == 2500


# ---------------------------------------------------------------------------
# ContextVar set/reset/get
# ---------------------------------------------------------------------------


class TestContextVar:
    def test_default_is_none(self):
        assert get_run_budget_tracker() is None

    def test_set_then_get(self):
        tracker = DaemonTokenTracker(lifetime_budget=100, daily_budget=None)
        token = set_run_budget_tracker(tracker)
        try:
            assert get_run_budget_tracker() is tracker
        finally:
            reset_run_budget_tracker(token)
        assert get_run_budget_tracker() is None

    def test_propagates_across_thread_pool_via_copy_context(self):
        """The whole point of using ContextVar over threading.local: state set
        in the main thread must be visible inside the timeout pool worker.

        ``_run_with_timeout`` (agent/executor_retry.py) submits via
        ``ctx.run(fn)`` after ``contextvars.copy_context()``, which is the path
        delegate tools hit when they fire during the parent's model call.
        """
        from initrunner.agent.executor_retry import _run_with_timeout

        tracker = DaemonTokenTracker(lifetime_budget=100, daily_budget=None)
        token = set_run_budget_tracker(tracker)
        try:
            seen = _run_with_timeout(get_run_budget_tracker, timeout=5.0)
        finally:
            reset_run_budget_tracker(token)

        assert seen is tracker


# ---------------------------------------------------------------------------
# InlineInvoker integration
# ---------------------------------------------------------------------------


def _write_role_file(tmp_path):
    role_file = tmp_path / "agent.yaml"
    role_file.write_text(
        textwrap.dedent("""\
            apiVersion: initrunner/v1
            kind: Agent
            metadata:
              name: sub-agent
            spec:
              role: You are helpful.
              model:
                provider: openai
                name: gpt-5-mini
        """)
    )
    return role_file


class TestInlineInvokerBudget:
    def test_records_subagent_usage_on_success(self, tmp_path):
        role_file = _write_role_file(tmp_path)
        tracker = DaemonTokenTracker(lifetime_budget=10000, daily_budget=None)

        mock_result = MagicMock()
        mock_result.success = True
        mock_result.output = "ok"
        mock_result.tokens_in = 60
        mock_result.tokens_out = 40
        mock_result.total_tokens = 100

        token = set_run_budget_tracker(tracker)
        try:
            with (
                patch("initrunner.agent.loader.load_and_build") as mock_load,
                patch("initrunner.agent.executor.execute_run") as mock_exec,
            ):
                mock_load.return_value = (MagicMock(), MagicMock())
                mock_load.return_value[0].metadata.name = "sub-agent"
                mock_exec.return_value = (mock_result, [])

                invoker = InlineInvoker(role_file, max_depth=3, timeout=60)
                out = invoker.invoke("hello")
        finally:
            reset_run_budget_tracker(token)

        assert out == "ok"
        # Reservation (1) + 100 actual - 1 reservation = 100
        assert tracker.total_consumed == 100

    def test_aborts_when_budget_exhausted_pre_subagent(self, tmp_path):
        role_file = _write_role_file(tmp_path)
        tracker = DaemonTokenTracker(lifetime_budget=100, daily_budget=None)
        # Pre-exhaust the tracker
        tracker.record_usage(60, 40)
        assert tracker.total_consumed == 100

        token = set_run_budget_tracker(tracker)
        try:
            with (
                patch("initrunner.agent.loader.load_and_build") as mock_load,
                patch("initrunner.agent.executor.execute_run") as mock_exec,
            ):
                mock_load.return_value = (MagicMock(), MagicMock())
                mock_load.return_value[0].metadata.name = "sub-agent"

                invoker = InlineInvoker(role_file, max_depth=3, timeout=60)
                out = invoker.invoke("hello")

                # execute_run should never have been called
                mock_exec.assert_not_called()
        finally:
            reset_run_budget_tracker(token)

        assert "[DELEGATION ERROR]" in out
        assert "Run token budget exhausted" in out

    def test_releases_reservation_on_exception(self, tmp_path):
        role_file = _write_role_file(tmp_path)
        tracker = DaemonTokenTracker(lifetime_budget=10000, daily_budget=None)
        before = tracker.total_consumed

        token = set_run_budget_tracker(tracker)
        try:
            with (
                patch("initrunner.agent.loader.load_and_build") as mock_load,
                patch("initrunner.agent.executor.execute_run") as mock_exec,
            ):
                mock_load.return_value = (MagicMock(), MagicMock())
                mock_load.return_value[0].metadata.name = "sub-agent"
                mock_exec.side_effect = RuntimeError("model exploded")

                invoker = InlineInvoker(role_file, max_depth=3, timeout=60)
                out = invoker.invoke("hello")
        finally:
            reset_run_budget_tracker(token)

        assert "[DELEGATION ERROR]" in out
        # The 1-token reservation taken by check_before_run must be released —
        # tracker should be back to its pre-call total.
        assert tracker.total_consumed == before

    def test_no_tracker_is_a_noop(self, tmp_path):
        """When no tracker is installed, InlineInvoker behaves as before."""
        role_file = _write_role_file(tmp_path)

        mock_result = MagicMock()
        mock_result.success = True
        mock_result.output = "ok"
        mock_result.tokens_in = 60
        mock_result.tokens_out = 40
        mock_result.total_tokens = 100

        # No set_run_budget_tracker call.
        assert get_run_budget_tracker() is None

        with (
            patch("initrunner.agent.loader.load_and_build") as mock_load,
            patch("initrunner.agent.executor.execute_run") as mock_exec,
        ):
            mock_load.return_value = (MagicMock(), MagicMock())
            mock_load.return_value[0].metadata.name = "sub-agent"
            mock_exec.return_value = (mock_result, [])

            invoker = InlineInvoker(role_file, max_depth=3, timeout=60)
            out = invoker.invoke("hello")

        assert out == "ok"
