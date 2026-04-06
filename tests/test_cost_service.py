"""Tests for the cost analytics service layer."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from initrunner.audit.logger import AuditLogger
from initrunner.services.cost import (
    AgentCostEntry,
    CostReport,
    cost_by_model_sync,
    cost_report_sync,
    cost_summary_sync,
)


@pytest.fixture()
def audit_db(tmp_path: Path) -> Path:
    return tmp_path / "test_audit.db"


def _insert(
    logger: AuditLogger,
    agent_name: str = "agent-a",
    model: str = "gpt-4o",
    provider: str = "openai",
    tokens_in: int = 100,
    tokens_out: int = 50,
    timestamp: str | None = None,
) -> None:
    ts = timestamp or datetime.now(UTC).isoformat()
    logger._conn.execute(
        """\
        INSERT INTO audit_log
            (run_id, agent_name, timestamp, user_prompt, model, provider,
             output, tokens_in, tokens_out, total_tokens, tool_calls,
             duration_ms, success)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            f"run-{ts}-{tokens_in}",
            agent_name,
            ts,
            "test",
            model,
            provider,
            "out",
            tokens_in,
            tokens_out,
            tokens_in + tokens_out,
            0,
            100,
            True,
        ),
    )
    logger._conn.commit()


class TestCostReport:
    def test_empty_db(self, audit_db: Path) -> None:
        report = cost_report_sync(audit_db=audit_db)
        assert report.entries == []
        assert report.total_runs == 0

    def test_nonexistent_db(self, tmp_path: Path) -> None:
        report = cost_report_sync(audit_db=tmp_path / "nope.db")
        assert report.entries == []

    def test_report_with_data(self, audit_db: Path) -> None:
        with AuditLogger(audit_db) as logger:
            _insert(logger, agent_name="a", tokens_in=1000, tokens_out=500)
            _insert(logger, agent_name="a", tokens_in=2000, tokens_out=1000)
            _insert(logger, agent_name="b", tokens_in=500, tokens_out=250)

        report = cost_report_sync(audit_db=audit_db)
        assert report.total_runs == 3
        assert len(report.entries) == 2
        # Agent "a" has more tokens, should be first
        assert report.entries[0].agent_name == "a"
        assert report.entries[0].run_count == 2
        assert report.entries[0].tokens_in == 3000

    def test_report_filters_by_agent(self, audit_db: Path) -> None:
        with AuditLogger(audit_db) as logger:
            _insert(logger, agent_name="a", tokens_in=100)
            _insert(logger, agent_name="b", tokens_in=200)

        report = cost_report_sync(agent_name="b", audit_db=audit_db)
        assert len(report.entries) == 1
        assert report.entries[0].agent_name == "b"

    def test_strict_na_aggregation(self, audit_db: Path) -> None:
        """If any group is unpriceable, total is None."""
        with AuditLogger(audit_db) as logger:
            _insert(logger, model="gpt-4o", provider="openai", tokens_in=100)
            _insert(logger, model="custom-model", provider="custom-provider", tokens_in=100)

        report = cost_report_sync(audit_db=audit_db)
        # One agent uses two models: one priceable, one not
        # The agent-level entry merges both, so its cost should be None
        # And the report total should also be None
        assert report.total_cost_usd is None


class TestCostByModel:
    def test_empty(self, audit_db: Path) -> None:
        assert cost_by_model_sync(audit_db=audit_db) == []

    def test_groups_by_model(self, audit_db: Path) -> None:
        with AuditLogger(audit_db) as logger:
            _insert(logger, model="gpt-4o", provider="openai", tokens_in=100)
            _insert(logger, model="claude-sonnet-4-20250514", provider="anthropic", tokens_in=200)

        entries = cost_by_model_sync(audit_db=audit_db)
        assert len(entries) == 2


class TestCostSummary:
    def test_empty(self, audit_db: Path) -> None:
        summary = cost_summary_sync(audit_db=audit_db)
        assert summary.top_agents == []
        assert summary.daily_trend == []

    def test_summary_with_data(self, audit_db: Path) -> None:
        with AuditLogger(audit_db) as logger:
            # Insert a record for today
            _insert(logger, agent_name="a", tokens_in=1000, tokens_out=500)

        summary = cost_summary_sync(audit_db=audit_db)
        assert len(summary.top_agents) == 1
        assert summary.top_agents[0].agent_name == "a"
        assert len(summary.daily_trend) >= 1
