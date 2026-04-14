"""Tests for per-tool cost attribution (audit + service layer)."""

from __future__ import annotations

import json
from pathlib import Path

from initrunner.agent.executor_models import RunResult
from initrunner.audit.logger import AuditLogger, AuditRecord


def _make_record(
    *,
    run_id: str = "run-1",
    agent_name: str = "test-agent",
    model: str = "gpt-5-mini",
    provider: str = "openai",
    tokens_in: int = 100,
    tokens_out: int = 50,
    tool_names: list[str] | None = None,
) -> AuditRecord:
    return AuditRecord(
        run_id=run_id,
        agent_name=agent_name,
        timestamp="2026-04-14T10:00:00+00:00",
        user_prompt="test prompt",
        model=model,
        provider=provider,
        output="test output",
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        total_tokens=tokens_in + tokens_out,
        tool_calls=len(tool_names) if tool_names else 0,
        duration_ms=500,
        success=True,
        tool_names=json.dumps(tool_names) if tool_names else None,
    )


class TestToolNamesMigration:
    def test_migration_idempotent(self, tmp_path: Path):
        """Creating AuditLogger twice on same DB does not raise."""
        db = tmp_path / "audit.db"
        with AuditLogger(db) as _logger1:
            pass
        with AuditLogger(db) as _logger2:
            pass

    def test_tool_names_column_exists(self, tmp_path: Path):
        """tool_names column exists after migration."""
        db = tmp_path / "audit.db"
        with AuditLogger(db) as logger:
            cols = [
                row[1] for row in logger._conn.execute("PRAGMA table_info(audit_log)").fetchall()
            ]
        assert "tool_names" in cols


class TestAuditRecordFromRun:
    def test_from_run_with_tools(self):
        """AuditRecord.from_run encodes tool_call_names as JSON."""
        from unittest.mock import MagicMock

        result = RunResult(
            run_id="r1",
            output="ok",
            tokens_in=10,
            tokens_out=5,
            total_tokens=15,
            tool_calls=2,
            duration_ms=100,
            success=True,
            tool_call_names=["search", "shell"],
        )
        role = MagicMock()
        role.metadata.name = "test"
        role.spec.model.name = "gpt-5-mini"
        role.spec.model.provider = "openai"

        record = AuditRecord.from_run(result, role, "test prompt")
        assert record.tool_names is not None
        assert json.loads(record.tool_names) == ["search", "shell"]

    def test_from_run_without_tools(self):
        """AuditRecord.from_run with empty tool_call_names sets tool_names to None."""
        from unittest.mock import MagicMock

        result = RunResult(run_id="r2", output="ok", tool_call_names=[])
        role = MagicMock()
        role.metadata.name = "test"
        role.spec.model.name = "gpt-5-mini"
        role.spec.model.provider = "openai"

        record = AuditRecord.from_run(result, role, "test prompt")
        assert record.tool_names is None


class TestLogAndQueryToolNames:
    def test_roundtrip(self, tmp_path: Path):
        """Log a record with tool_names and query it back via cost_by_tool."""
        db = tmp_path / "audit.db"
        record = _make_record(tool_names=["search", "web_reader"])
        with AuditLogger(db) as logger:
            logger.log(record)
            rows = logger.cost_by_tool()

        tool_names = {r["tool_name"] for r in rows}
        assert "search" in tool_names
        assert "web_reader" in tool_names

    def test_empty_db_returns_empty(self, tmp_path: Path):
        """cost_by_tool on empty DB returns empty list."""
        db = tmp_path / "audit.db"
        with AuditLogger(db) as logger:
            rows = logger.cost_by_tool()
        assert rows == []

    def test_null_tool_names_excluded(self, tmp_path: Path):
        """Records without tool_names are excluded from cost_by_tool."""
        db = tmp_path / "audit.db"
        record = _make_record(tool_names=None)
        with AuditLogger(db) as logger:
            logger.log(record)
            rows = logger.cost_by_tool()
        assert rows == []


class TestCostByToolNoOvercount:
    def test_repeated_tool_in_one_run(self, tmp_path: Path):
        """Same tool called 3x in one run: usage_count=3, tokens counted once."""
        db = tmp_path / "audit.db"
        record = _make_record(
            tool_names=["search", "search", "search"],
            tokens_in=100,
            tokens_out=50,
        )
        with AuditLogger(db) as logger:
            logger.log(record)
            rows = logger.cost_by_tool()

        assert len(rows) == 1
        assert rows[0]["tool_name"] == "search"
        assert rows[0]["usage_count"] == 3
        assert rows[0]["run_count"] == 1
        # Tokens should be counted once (not 3x)
        assert rows[0]["tokens_in"] == 100
        assert rows[0]["tokens_out"] == 50


class TestCostByToolFilters:
    def test_agent_name_filter(self, tmp_path: Path):
        db = tmp_path / "audit.db"
        r1 = _make_record(run_id="r1", agent_name="agent-a", tool_names=["search"])
        r2 = _make_record(run_id="r2", agent_name="agent-b", tool_names=["shell"])
        with AuditLogger(db) as logger:
            logger.log(r1)
            logger.log(r2)
            rows = logger.cost_by_tool(agent_name="agent-a")

        tool_names = {r["tool_name"] for r in rows}
        assert "search" in tool_names
        assert "shell" not in tool_names

    def test_since_filter(self, tmp_path: Path):
        db = tmp_path / "audit.db"
        r1 = _make_record(run_id="r1", tool_names=["search"])
        r1.timestamp = "2026-01-01T00:00:00+00:00"
        r2 = _make_record(run_id="r2", tool_names=["shell"])
        r2.timestamp = "2026-04-14T00:00:00+00:00"
        with AuditLogger(db) as logger:
            logger.log(r1)
            logger.log(r2)
            rows = logger.cost_by_tool(since="2026-04-01T00:00:00+00:00")

        tool_names = {r["tool_name"] for r in rows}
        assert "shell" in tool_names
        assert "search" not in tool_names
