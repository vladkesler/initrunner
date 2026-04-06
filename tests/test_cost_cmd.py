"""Tests for the cost CLI commands."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from initrunner.audit.logger import AuditLogger
from initrunner.cli.cost_cmd import app

runner = CliRunner()


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
) -> None:
    ts = datetime.now(UTC).isoformat()
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
    def test_no_db(self, tmp_path: Path) -> None:
        result = runner.invoke(app, ["report", "--audit-db", str(tmp_path / "nope.db")])
        assert result.exit_code == 1
        assert "not found" in result.output

    def test_empty_db(self, audit_db: Path) -> None:
        # Create the DB with no records
        with AuditLogger(audit_db):
            pass
        result = runner.invoke(app, ["report", "--audit-db", str(audit_db)])
        assert result.exit_code == 0
        assert "No audit records" in result.output

    def test_report_with_data(self, audit_db: Path) -> None:
        with AuditLogger(audit_db) as logger:
            _insert(logger, agent_name="my-agent", tokens_in=1000, tokens_out=500)

        result = runner.invoke(app, ["report", "--audit-db", str(audit_db)])
        assert result.exit_code == 0
        assert "my-agent" in result.output
        assert "1,000" in result.output

    def test_report_filter_by_agent(self, audit_db: Path) -> None:
        with AuditLogger(audit_db) as logger:
            _insert(logger, agent_name="a")
            _insert(logger, agent_name="b")

        result = runner.invoke(app, ["report", "--agent", "b", "--audit-db", str(audit_db)])
        assert result.exit_code == 0
        assert "b" in result.output


class TestCostSummary:
    def test_summary_with_data(self, audit_db: Path) -> None:
        with AuditLogger(audit_db) as logger:
            _insert(logger, agent_name="agent-x", tokens_in=2000, tokens_out=1000)

        result = runner.invoke(app, ["summary", "--audit-db", str(audit_db)])
        assert result.exit_code == 0
        assert "Cost Summary" in result.output
        assert "Today" in result.output


class TestCostByModel:
    def test_by_model_with_data(self, audit_db: Path) -> None:
        with AuditLogger(audit_db) as logger:
            _insert(logger, model="gpt-4o", provider="openai")

        result = runner.invoke(app, ["by-model", "--audit-db", str(audit_db)])
        assert result.exit_code == 0
        assert "gpt-4o" in result.output
        assert "openai" in result.output
