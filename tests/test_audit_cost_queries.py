"""Tests for AuditLogger cost aggregate queries."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from initrunner.audit.logger import AuditLogger


@pytest.fixture()
def audit_db(tmp_path: Path) -> Path:
    return tmp_path / "test_audit.db"


def _insert_record(
    logger: AuditLogger,
    agent_name: str = "agent-a",
    model: str = "gpt-4o",
    provider: str = "openai",
    tokens_in: int = 100,
    tokens_out: int = 50,
    timestamp: str | None = None,
) -> None:
    """Insert a test audit record directly."""
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
            f"run-{ts}",
            agent_name,
            ts,
            "test prompt",
            model,
            provider,
            "test output",
            tokens_in,
            tokens_out,
            tokens_in + tokens_out,
            0,
            100,
            True,
        ),
    )
    logger._conn.commit()


class TestCostByAgent:
    def test_empty_db(self, audit_db: Path) -> None:
        with AuditLogger(audit_db) as logger:
            assert logger.cost_by_agent() == []

    def test_groups_by_agent_model_provider(self, audit_db: Path) -> None:
        with AuditLogger(audit_db) as logger:
            _insert_record(logger, agent_name="a", model="gpt-4o", tokens_in=100, tokens_out=50)
            _insert_record(logger, agent_name="a", model="gpt-4o", tokens_in=200, tokens_out=100)
            _insert_record(
                logger,
                agent_name="b",
                model="claude-sonnet-4-20250514",
                provider="anthropic",
                tokens_in=50,
                tokens_out=25,
            )

            rows = logger.cost_by_agent()
            assert len(rows) == 2

            # First row should be agent "a" (more tokens)
            assert rows[0]["agent_name"] == "a"
            assert rows[0]["tokens_in"] == 300
            assert rows[0]["tokens_out"] == 150
            assert rows[0]["run_count"] == 2

            assert rows[1]["agent_name"] == "b"
            assert rows[1]["tokens_in"] == 50
            assert rows[1]["run_count"] == 1

    def test_filters_by_agent_name(self, audit_db: Path) -> None:
        with AuditLogger(audit_db) as logger:
            _insert_record(logger, agent_name="a", tokens_in=100, tokens_out=50)
            _insert_record(logger, agent_name="b", tokens_in=200, tokens_out=100)

            rows = logger.cost_by_agent(agent_name="b")
            assert len(rows) == 1
            assert rows[0]["agent_name"] == "b"

    def test_filters_by_time_range(self, audit_db: Path) -> None:
        with AuditLogger(audit_db) as logger:
            old = (datetime.now(UTC) - timedelta(days=10)).isoformat()
            recent = datetime.now(UTC).isoformat()
            _insert_record(logger, agent_name="a", tokens_in=100, timestamp=old)
            _insert_record(logger, agent_name="a", tokens_in=200, timestamp=recent)

            cutoff = (datetime.now(UTC) - timedelta(days=5)).isoformat()
            rows = logger.cost_by_agent(since=cutoff)
            assert len(rows) == 1
            assert rows[0]["tokens_in"] == 200


class TestCostByDay:
    def test_empty_db(self, audit_db: Path) -> None:
        with AuditLogger(audit_db) as logger:
            assert logger.cost_by_day() == []

    def test_groups_by_date(self, audit_db: Path) -> None:
        with AuditLogger(audit_db) as logger:
            day1 = "2026-04-01T10:00:00+00:00"
            day2 = "2026-04-02T10:00:00+00:00"
            _insert_record(logger, tokens_in=100, timestamp=day1)
            _insert_record(logger, tokens_in=200, timestamp=day1)
            _insert_record(logger, tokens_in=300, timestamp=day2)

            rows = logger.cost_by_day()
            assert len(rows) == 2
            # Ordered by date ASC
            assert rows[0]["date"] == "2026-04-01"
            assert rows[0]["tokens_in"] == 300
            assert rows[0]["run_count"] == 2
            assert rows[1]["date"] == "2026-04-02"
            assert rows[1]["tokens_in"] == 300
            assert rows[1]["run_count"] == 1

    def test_filters_by_agent(self, audit_db: Path) -> None:
        with AuditLogger(audit_db) as logger:
            ts = "2026-04-01T10:00:00+00:00"
            _insert_record(logger, agent_name="a", tokens_in=100, timestamp=ts)
            _insert_record(logger, agent_name="b", tokens_in=200, timestamp=ts)

            rows = logger.cost_by_day(agent_name="a")
            assert len(rows) == 1
            assert rows[0]["tokens_in"] == 100


class TestCostByModel:
    def test_empty_db(self, audit_db: Path) -> None:
        with AuditLogger(audit_db) as logger:
            assert logger.cost_by_model() == []

    def test_groups_by_model_provider(self, audit_db: Path) -> None:
        with AuditLogger(audit_db) as logger:
            _insert_record(logger, model="gpt-4o", provider="openai", tokens_in=100)
            _insert_record(logger, model="gpt-4o", provider="openai", tokens_in=200)
            _insert_record(
                logger,
                model="claude-sonnet-4-20250514",
                provider="anthropic",
                tokens_in=500,
            )

            rows = logger.cost_by_model()
            assert len(rows) == 2
            # Anthropic model has more tokens, should be first
            assert rows[0]["model"] == "claude-sonnet-4-20250514"
            assert rows[0]["tokens_in"] == 500
            assert rows[1]["model"] == "gpt-4o"
            assert rows[1]["tokens_in"] == 300

    def test_filters_by_time_range(self, audit_db: Path) -> None:
        with AuditLogger(audit_db) as logger:
            old = "2026-03-01T10:00:00+00:00"
            recent = "2026-04-05T10:00:00+00:00"
            _insert_record(logger, model="gpt-4o", tokens_in=100, timestamp=old)
            _insert_record(logger, model="gpt-4o", tokens_in=200, timestamp=recent)

            rows = logger.cost_by_model(since="2026-04-01T00:00:00+00:00")
            assert len(rows) == 1
            assert rows[0]["tokens_in"] == 200
