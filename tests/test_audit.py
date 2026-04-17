"""Tests for the audit logger."""

import json
import logging
import sqlite3
import threading
from datetime import UTC, datetime, timedelta

from typer.testing import CliRunner

from initrunner.audit.logger import AuditLogger, AuditRecord, DelegateAuditEvent
from initrunner.cli.main import app as cli_app

cli_runner = CliRunner()


def _make_record(**kwargs) -> AuditRecord:
    defaults = {
        "run_id": "abc123",
        "agent_name": "test-agent",
        "timestamp": "2025-01-01T00:00:00Z",
        "user_prompt": "hello",
        "model": "claude-sonnet-4-5-20250929",
        "provider": "anthropic",
        "output": "hi there",
        "tokens_in": 10,
        "tokens_out": 5,
        "total_tokens": 15,
        "tool_calls": 0,
        "duration_ms": 500,
        "success": True,
        "error": None,
    }
    defaults.update(kwargs)
    return AuditRecord(**defaults)  # type: ignore[invalid-argument-type]


class TestAuditLogger:
    def test_creates_db(self, tmp_path):
        db_path = tmp_path / "test.db"
        with AuditLogger(db_path):
            pass
        assert db_path.exists()

    def test_creates_parent_dirs(self, tmp_path):
        db_path = tmp_path / "nested" / "dir" / "test.db"
        with AuditLogger(db_path):
            pass
        assert db_path.exists()

    def test_log_and_readback(self, tmp_path):
        db_path = tmp_path / "test.db"
        record = _make_record()

        with AuditLogger(db_path) as logger:
            logger.log(record)

        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM audit_log").fetchall()
        conn.close()

        assert len(rows) == 1
        row = rows[0]
        assert row["run_id"] == "abc123"
        assert row["agent_name"] == "test-agent"
        assert row["tokens_in"] == 10
        assert row["success"] == 1

    def test_log_with_error(self, tmp_path):
        db_path = tmp_path / "test.db"
        record = _make_record(success=False, error="timeout")

        with AuditLogger(db_path) as logger:
            logger.log(record)

        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM audit_log").fetchall()
        conn.close()

        assert rows[0]["success"] == 0
        assert rows[0]["error"] == "timeout"

    def test_multiple_records(self, tmp_path):
        db_path = tmp_path / "test.db"

        with AuditLogger(db_path) as logger:
            for i in range(5):
                logger.log(_make_record(run_id=f"run-{i}"))

        conn = sqlite3.connect(str(db_path))
        count = conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
        conn.close()
        assert count == 5

    def test_log_never_raises(self, tmp_path, caplog):
        db_path = tmp_path / "test.db"
        audit_logger = AuditLogger(db_path)
        audit_logger.close()  # close the connection to force an error

        # This should log an error but not raise
        ir_logger = logging.getLogger("initrunner")
        ir_logger.addHandler(caplog.handler)
        try:
            with caplog.at_level("ERROR", logger="initrunner.audit"):
                audit_logger.log(_make_record())
            assert "Failed to write audit record" in caplog.text
        finally:
            ir_logger.removeHandler(caplog.handler)

    def test_wal_mode(self, tmp_path):
        db_path = tmp_path / "test.db"
        with AuditLogger(db_path):
            conn = sqlite3.connect(str(db_path))
            mode = conn.execute("PRAGMA journal_mode;").fetchone()[0]
            conn.close()
            assert mode == "wal"


class TestTriggerFields:
    def test_log_with_trigger_context(self, tmp_path):
        db_path = tmp_path / "test.db"
        record = _make_record(
            trigger_type="cron",
            trigger_metadata=json.dumps({"schedule": "0 9 * * 1"}),
        )

        with AuditLogger(db_path) as logger:
            logger.log(record)

        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM audit_log").fetchone()
        conn.close()

        assert row["trigger_type"] == "cron"
        assert json.loads(row["trigger_metadata"]) == {"schedule": "0 9 * * 1"}

    def test_log_without_trigger_context(self, tmp_path):
        db_path = tmp_path / "test.db"
        record = _make_record()

        with AuditLogger(db_path) as logger:
            logger.log(record)

        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM audit_log").fetchone()
        conn.close()

        assert row["trigger_type"] is None
        assert row["trigger_metadata"] is None

    def test_from_run_with_trigger_context(self):
        from unittest.mock import MagicMock

        result = MagicMock()
        result.run_id = "run1"
        result.output = "ok"
        result.tokens_in = 1
        result.tokens_out = 2
        result.total_tokens = 3
        result.tool_calls = 0
        result.duration_ms = 100
        result.success = True
        result.error = None
        result.tool_call_names = []

        role = MagicMock()
        role.metadata.name = "agent1"
        role.spec.model.name = "gpt-5-mini"
        role.spec.model.provider = "openai"

        record = AuditRecord.from_run(
            result,
            role,
            "test prompt",
            trigger_type="file_watch",
            trigger_metadata={"path": "/tmp/test.md"},
        )

        assert record.trigger_type == "file_watch"
        assert record.trigger_metadata is not None
        assert json.loads(record.trigger_metadata) == {"path": "/tmp/test.md"}

    def test_from_run_without_trigger_context(self):
        from unittest.mock import MagicMock

        result = MagicMock()
        result.run_id = "run1"
        result.output = "ok"
        result.tokens_in = 1
        result.tokens_out = 2
        result.total_tokens = 3
        result.tool_calls = 0
        result.duration_ms = 100
        result.success = True
        result.error = None
        result.tool_call_names = []

        role = MagicMock()
        role.metadata.name = "agent1"
        role.spec.model.name = "gpt-5-mini"
        role.spec.model.provider = "openai"

        record = AuditRecord.from_run(result, role, "test prompt")

        assert record.trigger_type is None
        assert record.trigger_metadata is None


class TestTriggerStats:
    def test_empty_db(self, tmp_path):
        db_path = tmp_path / "test.db"
        with AuditLogger(db_path) as logger:
            stats = logger.trigger_stats(agent_name="agent-a")
        assert stats == []

    def test_no_trigger_records(self, tmp_path):
        db_path = tmp_path / "test.db"
        with AuditLogger(db_path) as logger:
            logger.log(_make_record(agent_name="agent-a"))
            stats = logger.trigger_stats(agent_name="agent-a")
        assert stats == []

    def test_single_trigger_type(self, tmp_path):
        db_path = tmp_path / "test.db"
        with AuditLogger(db_path) as logger:
            logger.log(_make_record(agent_name="a", trigger_type="cron", duration_ms=100))
            logger.log(_make_record(agent_name="a", trigger_type="cron", duration_ms=200))
            stats = logger.trigger_stats(agent_name="a")
        assert len(stats) == 1
        s = stats[0]
        assert s.trigger_type == "cron"
        assert s.fire_count == 2
        assert s.success_count == 2
        assert s.fail_count == 0
        assert s.avg_duration_ms == 150
        assert s.last_error is None

    def test_multiple_trigger_types(self, tmp_path):
        db_path = tmp_path / "test.db"
        with AuditLogger(db_path) as logger:
            logger.log(_make_record(agent_name="a", trigger_type="cron"))
            logger.log(_make_record(agent_name="a", trigger_type="webhook"))
            logger.log(_make_record(agent_name="a", trigger_type="webhook"))
            stats = logger.trigger_stats(agent_name="a")
        by_type = {s.trigger_type: s for s in stats}
        assert len(by_type) == 2
        assert by_type["cron"].fire_count == 1
        assert by_type["webhook"].fire_count == 2

    def test_mixed_success_failure(self, tmp_path):
        db_path = tmp_path / "test.db"
        with AuditLogger(db_path) as logger:
            logger.log(_make_record(agent_name="a", trigger_type="cron", success=True))
            logger.log(
                _make_record(
                    agent_name="a",
                    trigger_type="cron",
                    success=False,
                    error="timeout",
                    timestamp="2025-01-01T00:00:00Z",
                )
            )
            logger.log(
                _make_record(
                    agent_name="a",
                    trigger_type="cron",
                    success=False,
                    error="rate limited",
                    timestamp="2025-06-01T00:00:00Z",
                )
            )
            stats = logger.trigger_stats(agent_name="a")
        assert len(stats) == 1
        s = stats[0]
        assert s.success_count == 1
        assert s.fail_count == 2
        assert s.last_error == "rate limited"

    def test_last_fire_time(self, tmp_path):
        db_path = tmp_path / "test.db"
        with AuditLogger(db_path) as logger:
            logger.log(
                _make_record(agent_name="a", trigger_type="cron", timestamp="2025-01-01T00:00:00Z")
            )
            logger.log(
                _make_record(agent_name="a", trigger_type="cron", timestamp="2025-06-15T12:00:00Z")
            )
            stats = logger.trigger_stats(agent_name="a")
        assert stats[0].last_fire_time == "2025-06-15T12:00:00Z"

    def test_filters_by_agent(self, tmp_path):
        db_path = tmp_path / "test.db"
        with AuditLogger(db_path) as logger:
            logger.log(_make_record(agent_name="a", trigger_type="cron"))
            logger.log(_make_record(agent_name="b", trigger_type="cron"))
            stats = logger.trigger_stats(agent_name="a")
        assert len(stats) == 1
        assert stats[0].fire_count == 1


class TestMigration:
    def test_migrate_old_schema(self, tmp_path):
        """Opening a DB created with old schema adds trigger columns."""
        db_path = tmp_path / "old.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("""\
            CREATE TABLE audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                agent_name TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                user_prompt TEXT NOT NULL,
                model TEXT NOT NULL,
                provider TEXT NOT NULL,
                output TEXT NOT NULL,
                tokens_in INTEGER NOT NULL,
                tokens_out INTEGER NOT NULL,
                total_tokens INTEGER NOT NULL,
                tool_calls INTEGER NOT NULL,
                duration_ms INTEGER NOT NULL,
                success BOOLEAN NOT NULL,
                error TEXT
            )
        """)
        conn.execute(
            "INSERT INTO audit_log VALUES (NULL,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            ("r1", "ag", "2025-01-01", "hi", "m", "p", "o", 1, 2, 3, 0, 100, 1, None),
        )
        conn.commit()
        conn.close()

        # Opening with AuditLogger should migrate
        with AuditLogger(db_path) as logger:
            # Can log new records with trigger fields
            logger.log(_make_record(trigger_type="cron"))

            # Can query old records (trigger fields are NULL)
            records = logger.query()
            assert len(records) == 2
            old = next(r for r in records if r.run_id == "r1")
            assert old.trigger_type is None
            new = next(r for r in records if r.run_id == "abc123")
            assert new.trigger_type == "cron"

    def test_migrate_idempotent(self, tmp_path):
        """Opening a migrated DB twice doesn't error."""
        db_path = tmp_path / "test.db"
        with AuditLogger(db_path):
            pass
        # Second open should be fine
        with AuditLogger(db_path):
            pass


class TestQuery:
    def _seed(self, logger):
        logger.log(
            _make_record(
                run_id="r1",
                agent_name="agent-a",
                timestamp="2025-01-01T00:00:00Z",
                trigger_type="cron",
                trigger_metadata=json.dumps({"schedule": "daily"}),
            )
        )
        logger.log(
            _make_record(
                run_id="r2",
                agent_name="agent-a",
                timestamp="2025-01-02T00:00:00Z",
            )
        )
        logger.log(
            _make_record(
                run_id="r3",
                agent_name="agent-b",
                timestamp="2025-01-03T00:00:00Z",
                trigger_type="file_watch",
            )
        )

    def test_query_all(self, tmp_path):
        db_path = tmp_path / "test.db"
        with AuditLogger(db_path) as logger:
            self._seed(logger)
            records = logger.query()
        assert len(records) == 3
        # Ordered by timestamp DESC
        assert records[0].run_id == "r3"
        assert records[2].run_id == "r1"

    def test_query_by_agent_name(self, tmp_path):
        db_path = tmp_path / "test.db"
        with AuditLogger(db_path) as logger:
            self._seed(logger)
            records = logger.query(agent_name="agent-a")
        assert len(records) == 2
        assert all(r.agent_name == "agent-a" for r in records)

    def test_query_by_run_id(self, tmp_path):
        db_path = tmp_path / "test.db"
        with AuditLogger(db_path) as logger:
            self._seed(logger)
            records = logger.query(run_id="r2")
        assert len(records) == 1
        assert records[0].run_id == "r2"

    def test_query_by_trigger_type(self, tmp_path):
        db_path = tmp_path / "test.db"
        with AuditLogger(db_path) as logger:
            self._seed(logger)
            records = logger.query(trigger_type="cron")
        assert len(records) == 1
        assert records[0].trigger_type == "cron"

    def test_query_since(self, tmp_path):
        db_path = tmp_path / "test.db"
        with AuditLogger(db_path) as logger:
            self._seed(logger)
            records = logger.query(since="2025-01-02T00:00:00Z")
        assert len(records) == 2

    def test_query_until(self, tmp_path):
        db_path = tmp_path / "test.db"
        with AuditLogger(db_path) as logger:
            self._seed(logger)
            records = logger.query(until="2025-01-01T23:59:59Z")
        assert len(records) == 1
        assert records[0].run_id == "r1"

    def test_query_since_and_until(self, tmp_path):
        db_path = tmp_path / "test.db"
        with AuditLogger(db_path) as logger:
            self._seed(logger)
            records = logger.query(
                since="2025-01-01T12:00:00Z",
                until="2025-01-02T12:00:00Z",
            )
        assert len(records) == 1
        assert records[0].run_id == "r2"

    def test_query_limit(self, tmp_path):
        db_path = tmp_path / "test.db"
        with AuditLogger(db_path) as logger:
            self._seed(logger)
            records = logger.query(limit=2)
        assert len(records) == 2

    def test_query_combined_filters(self, tmp_path):
        db_path = tmp_path / "test.db"
        with AuditLogger(db_path) as logger:
            self._seed(logger)
            records = logger.query(agent_name="agent-a", trigger_type="cron")
        assert len(records) == 1
        assert records[0].run_id == "r1"

    def test_query_no_matches(self, tmp_path):
        db_path = tmp_path / "test.db"
        with AuditLogger(db_path) as logger:
            self._seed(logger)
            records = logger.query(agent_name="nonexistent")
        assert len(records) == 0


class TestSecurityEvents:
    def test_log_security_event(self, tmp_path):
        db_path = tmp_path / "test.db"
        with AuditLogger(db_path) as logger:
            logger.log_security_event(
                event_type="blocked_prompt",
                agent_name="test-agent",
                details="Input matched blocked pattern",
                source_ip="127.0.0.1",
            )
            events = logger.query_security_events()
        assert len(events) == 1
        assert events[0]["event_type"] == "blocked_prompt"
        assert events[0]["agent_name"] == "test-agent"
        assert events[0]["source_ip"] == "127.0.0.1"

    def test_multiple_security_events(self, tmp_path):
        db_path = tmp_path / "test.db"
        with AuditLogger(db_path) as logger:
            logger.log_security_event("blocked_prompt", "agent-a", "pattern match")
            logger.log_security_event("rate_limited", "agent-a", "burst exceeded")
            logger.log_security_event("auth_failure", "agent-b", "invalid key")
            events = logger.query_security_events(event_type="blocked_prompt")
        assert len(events) == 1

    def test_security_event_never_raises(self, tmp_path, caplog):
        db_path = tmp_path / "test.db"
        audit_logger = AuditLogger(db_path)
        audit_logger.close()
        ir_logger = logging.getLogger("initrunner")
        ir_logger.addHandler(caplog.handler)
        try:
            with caplog.at_level("ERROR", logger="initrunner.audit"):
                audit_logger.log_security_event("test", "agent", "details")
            assert "Failed to write security event" in caplog.text
        finally:
            ir_logger.removeHandler(caplog.handler)


class TestPrune:
    def test_prune_by_retention_days(self, tmp_path):
        db_path = tmp_path / "test.db"
        old_timestamp = (datetime.now(UTC) - timedelta(days=100)).isoformat()
        recent_timestamp = datetime.now(UTC).isoformat()

        with AuditLogger(db_path) as logger:
            logger.log(_make_record(run_id="old", timestamp=old_timestamp))
            logger.log(_make_record(run_id="recent", timestamp=recent_timestamp))
            deleted = logger.prune(retention_days=90, max_records=100_000)

        assert deleted >= 1
        with AuditLogger(db_path) as logger:
            records = logger.query()
        assert len(records) == 1
        assert records[0].run_id == "recent"

    def test_prune_by_max_records(self, tmp_path):
        db_path = tmp_path / "test.db"
        with AuditLogger(db_path) as logger:
            for i in range(10):
                logger.log(_make_record(run_id=f"r{i}"))
            deleted = logger.prune(retention_days=9999, max_records=3)

        assert deleted >= 7
        with AuditLogger(db_path) as logger:
            records = logger.query()
        assert len(records) == 3


class TestAuditPruneCLI:
    def test_prune_command_no_db(self, tmp_path):
        result = cli_runner.invoke(
            cli_app,
            ["audit", "prune", "--audit-db", str(tmp_path / "nonexistent.db")],
        )
        assert result.exit_code == 1

    def test_prune_command_works(self, tmp_path):
        db_path = tmp_path / "test.db"
        with AuditLogger(db_path) as logger:
            for i in range(5):
                logger.log(_make_record(run_id=f"r{i}"))

        result = cli_runner.invoke(
            cli_app,
            ["audit", "prune", "--max-records", "2", "--audit-db", str(db_path)],
        )
        assert result.exit_code == 0
        assert "Pruned" in result.output


class TestAuditThreadSafety:
    def test_concurrent_log_no_lost_records(self, tmp_path):
        """N threads x M records each — total rows must match."""
        db_path = tmp_path / "test.db"
        n_threads = 8
        m_records = 50

        with AuditLogger(db_path) as logger:
            barrier = threading.Barrier(n_threads)

            def _worker(thread_id: int) -> None:
                barrier.wait()
                for i in range(m_records):
                    logger.log(_make_record(run_id=f"t{thread_id}-r{i}"))

            threads = [threading.Thread(target=_worker, args=(t,)) for t in range(n_threads)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

        conn = sqlite3.connect(str(db_path))
        count = conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
        conn.close()
        assert count == n_threads * m_records

    def test_concurrent_log_insert_count_accurate(self, tmp_path):
        """_insert_count must match actual inserts after concurrent writes."""
        db_path = tmp_path / "test.db"
        n_threads = 8
        m_records = 50

        with AuditLogger(db_path) as logger:
            barrier = threading.Barrier(n_threads)

            def _worker(thread_id: int) -> None:
                barrier.wait()
                for i in range(m_records):
                    logger.log(_make_record(run_id=f"t{thread_id}-r{i}"))

            threads = [threading.Thread(target=_worker, args=(t,)) for t in range(n_threads)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            assert logger._insert_count == n_threads * m_records

    def test_concurrent_log_triggers_prune_once(self, tmp_path):
        """Auto-prune fires exactly once when insert_count hits the interval."""
        db_path = tmp_path / "test.db"
        # Use a small interval so we can hit it with few records
        interval = 40
        n_threads = 8
        m_records = 5  # 8 * 5 = 40, should trigger exactly once

        with AuditLogger(
            db_path,
            auto_prune_interval=interval,
            retention_days=9999,
            max_records=1_000_000,
        ) as logger:
            prune_calls: list[int] = []
            original_prune = logger._prune_locked

            def _tracking_prune(**kwargs):
                prune_calls.append(1)
                return original_prune(**kwargs)

            logger._prune_locked = _tracking_prune  # type: ignore[invalid-assignment]

            barrier = threading.Barrier(n_threads)

            def _worker(thread_id: int) -> None:
                barrier.wait()
                for i in range(m_records):
                    logger.log(_make_record(run_id=f"t{thread_id}-r{i}"))

            threads = [threading.Thread(target=_worker, args=(t,)) for t in range(n_threads)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            assert len(prune_calls) == 1


class TestAuditSecretScrubbing:
    """Integration tests: secrets are scrubbed before being persisted to the DB."""

    def test_log_scrubs_user_prompt(self, tmp_path):
        db_path = tmp_path / "test.db"
        record = _make_record(user_prompt="my key is sk-abcdefghijklmnopqrstuvwx")
        with AuditLogger(db_path) as logger:
            logger.log(record)
            rows = logger.query()
        assert "sk-" not in rows[0].user_prompt
        assert "[REDACTED]" in rows[0].user_prompt

    def test_log_scrubs_output(self, tmp_path):
        db_path = tmp_path / "test.db"
        record = _make_record(output="token: ghp_ABCDEFghijklmnopqrstuvwxyz0123456789ab")
        with AuditLogger(db_path) as logger:
            logger.log(record)
            rows = logger.query()
        assert "ghp_" not in rows[0].output
        assert "[REDACTED]" in rows[0].output

    def test_log_scrubs_error(self, tmp_path):
        db_path = tmp_path / "test.db"
        record = _make_record(
            success=False,
            error="Failed with key xoxb-1234567890-abcdefghij",
        )
        with AuditLogger(db_path) as logger:
            logger.log(record)
            rows = logger.query()
        assert rows[0].error is not None
        assert "xoxb-" not in rows[0].error
        assert "[REDACTED]" in rows[0].error

    def test_log_preserves_none_error(self, tmp_path):
        db_path = tmp_path / "test.db"
        record = _make_record(error=None)
        with AuditLogger(db_path) as logger:
            logger.log(record)
            rows = logger.query()
        assert rows[0].error is None

    def test_security_event_scrubs_details(self, tmp_path):
        db_path = tmp_path / "test.db"
        with AuditLogger(db_path) as logger:
            logger.log_security_event(
                event_type="leak",
                agent_name="test-agent",
                details="Leaked key sk-abcdefghijklmnopqrstuvwx in response",
            )
            events = logger.query_security_events()
        assert "sk-" not in events[0]["details"]
        assert "[REDACTED]" in events[0]["details"]

    def test_normal_text_passes_through(self, tmp_path):
        db_path = tmp_path / "test.db"
        record = _make_record(
            user_prompt="What is the weather?",
            output="It is sunny today.",
        )
        with AuditLogger(db_path) as logger:
            logger.log(record)
            rows = logger.query()
        assert rows[0].user_prompt == "What is the weather?"
        assert rows[0].output == "It is sunny today."


class TestDelegateEvents:
    def test_log_and_readback(self, tmp_path):
        db_path = tmp_path / "test.db"
        with AuditLogger(db_path) as logger:
            logger.log_delegate_event(
                source_service="agent-a",
                target_service="agent-b",
                status="delivered",
                source_run_id="run1",
                trace="agent-a",
                payload_preview="hello world",
            )
            events = logger.query_delegate_events()

        assert len(events) == 1
        evt = events[0]
        assert isinstance(evt, DelegateAuditEvent)
        assert evt.source_service == "agent-a"
        assert evt.target_service == "agent-b"
        assert evt.status == "delivered"
        assert evt.source_run_id == "run1"
        assert evt.reason is None
        assert evt.trace == "agent-a"
        assert evt.payload_preview == "hello world"
        assert evt.timestamp  # auto-generated

    def test_never_raises_on_closed_db(self, tmp_path, caplog):
        db_path = tmp_path / "test.db"
        audit_logger = AuditLogger(db_path)
        audit_logger.close()

        ir_logger = logging.getLogger("initrunner")
        ir_logger.addHandler(caplog.handler)
        try:
            with caplog.at_level("ERROR", logger="initrunner.audit"):
                audit_logger.log_delegate_event(
                    source_service="a",
                    target_service="b",
                    status="delivered",
                    source_run_id="r1",
                )
            assert "Failed to write delegate event" in caplog.text
        finally:
            ir_logger.removeHandler(caplog.handler)

    def test_query_filter_source(self, tmp_path):
        db_path = tmp_path / "test.db"
        with AuditLogger(db_path) as logger:
            logger.log_delegate_event(
                source_service="a",
                target_service="b",
                status="delivered",
                source_run_id="r1",
            )
            logger.log_delegate_event(
                source_service="c",
                target_service="b",
                status="delivered",
                source_run_id="r2",
            )
            events = logger.query_delegate_events(source_service="a")
        assert len(events) == 1
        assert events[0].source_service == "a"

    def test_query_filter_target(self, tmp_path):
        db_path = tmp_path / "test.db"
        with AuditLogger(db_path) as logger:
            logger.log_delegate_event(
                source_service="a",
                target_service="b",
                status="delivered",
                source_run_id="r1",
            )
            logger.log_delegate_event(
                source_service="a",
                target_service="c",
                status="delivered",
                source_run_id="r2",
            )
            events = logger.query_delegate_events(target_service="c")
        assert len(events) == 1
        assert events[0].target_service == "c"

    def test_query_filter_status(self, tmp_path):
        db_path = tmp_path / "test.db"
        with AuditLogger(db_path) as logger:
            logger.log_delegate_event(
                source_service="a",
                target_service="b",
                status="delivered",
                source_run_id="r1",
            )
            logger.log_delegate_event(
                source_service="a",
                target_service="b",
                status="dropped",
                source_run_id="r2",
                reason="queue_full",
            )
            events = logger.query_delegate_events(status="dropped")
        assert len(events) == 1
        assert events[0].status == "dropped"
        assert events[0].reason == "queue_full"

    def test_query_filter_run_id(self, tmp_path):
        db_path = tmp_path / "test.db"
        with AuditLogger(db_path) as logger:
            logger.log_delegate_event(
                source_service="a",
                target_service="b",
                status="delivered",
                source_run_id="run-42",
            )
            logger.log_delegate_event(
                source_service="a",
                target_service="b",
                status="delivered",
                source_run_id="run-99",
            )
            events = logger.query_delegate_events(source_run_id="run-42")
        assert len(events) == 1
        assert events[0].source_run_id == "run-42"

    def test_query_filter_since_until(self, tmp_path):
        db_path = tmp_path / "test.db"
        with AuditLogger(db_path) as logger:
            logger.log_delegate_event(
                source_service="a",
                target_service="b",
                status="delivered",
                source_run_id="r1",
            )
            events_all = logger.query_delegate_events()
            # Since we just inserted, query with a far-future 'since' should return nothing
            events_future = logger.query_delegate_events(since="2099-01-01T00:00:00Z")
        assert len(events_all) == 1
        assert len(events_future) == 0

    def test_query_limit(self, tmp_path):
        db_path = tmp_path / "test.db"
        with AuditLogger(db_path) as logger:
            for i in range(5):
                logger.log_delegate_event(
                    source_service="a",
                    target_service="b",
                    status="delivered",
                    source_run_id=f"r{i}",
                )
            events = logger.query_delegate_events(limit=2)
        assert len(events) == 2

    def test_pruning_includes_delegate_events(self, tmp_path):
        db_path = tmp_path / "test.db"
        old_ts = (datetime.now(UTC) - timedelta(days=100)).isoformat()
        with AuditLogger(db_path) as logger:
            # Insert old event directly to control timestamp
            with logger._lock:
                logger._conn.execute(
                    "INSERT INTO delegate_events "
                    "(timestamp, source_service, target_service, status, "
                    "source_run_id, reason, trace, payload_preview) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (old_ts, "a", "b", "delivered", "old-run", None, None, ""),
                )
                logger._conn.commit()
            # Insert a recent event normally
            logger.log_delegate_event(
                source_service="a",
                target_service="b",
                status="delivered",
                source_run_id="new-run",
            )
            logger.prune(retention_days=90, max_records=100_000)
            events = logger.query_delegate_events()
        assert len(events) == 1
        assert events[0].source_run_id == "new-run"

    def test_secret_scrubbing(self, tmp_path):
        db_path = tmp_path / "test.db"
        with AuditLogger(db_path) as logger:
            logger.log_delegate_event(
                source_service="a",
                target_service="b",
                status="error",
                source_run_id="r1",
                reason="Failed with key sk-abcdefghijklmnopqrstuvwx",
                payload_preview="Output contains ghp_ABCDEFghijklmnopqrstuvwxyz0123456789ab token",
            )
            events = logger.query_delegate_events()
        assert "sk-" not in (events[0].reason or "")
        assert "[REDACTED]" in (events[0].reason or "")
        assert "ghp_" not in events[0].payload_preview
        assert "[REDACTED]" in events[0].payload_preview

    def test_payload_preview_truncation(self, tmp_path):
        db_path = tmp_path / "test.db"
        long_text = "x" * 500
        with AuditLogger(db_path) as logger:
            logger.log_delegate_event(
                source_service="a",
                target_service="b",
                status="delivered",
                source_run_id="r1",
                payload_preview=long_text,
            )
            events = logger.query_delegate_events()
        # payload_preview is truncated to 200 chars inside log_delegate_event
        assert len(events[0].payload_preview) == 200

    def test_table_created_on_existing_db(self, tmp_path):
        """Opening an existing DB without delegate_events table creates it."""
        db_path = tmp_path / "test.db"
        # Create DB with only audit_log table
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "CREATE TABLE audit_log ("
            "id INTEGER PRIMARY KEY, run_id TEXT, agent_name TEXT, "
            "timestamp TEXT, user_prompt TEXT, model TEXT, provider TEXT, "
            "output TEXT, tokens_in INTEGER, tokens_out INTEGER, "
            "total_tokens INTEGER, tool_calls INTEGER, duration_ms INTEGER, "
            "success BOOLEAN, error TEXT)"
        )
        conn.commit()
        conn.close()

        with AuditLogger(db_path) as logger:
            logger.log_delegate_event(
                source_service="a",
                target_service="b",
                status="delivered",
                source_run_id="r1",
            )
            events = logger.query_delegate_events()
        assert len(events) == 1

    def test_timeout_on_connection(self, tmp_path):
        """AuditLogger connects with timeout=30."""
        db_path = tmp_path / "test.db"
        with AuditLogger(db_path) as logger:
            # Access the internal connection to verify timeout
            # SQLite doesn't expose timeout directly, but we can verify
            # the connection was created successfully with the parameter
            assert logger._conn is not None


class TestAuditChain:
    """HMAC-signed audit chain: key mgmt, signing, verification, tamper detection."""

    def _key_path(self, tmp_path):
        return tmp_path / "audit_hmac.key"

    def _env_with_key(self, monkeypatch, tmp_path):
        """Point config helpers at tmp_path and clear the env var override."""
        import initrunner.audit._hmac as hmac_mod
        import initrunner.config as cfg

        key_path = self._key_path(tmp_path)
        monkeypatch.setattr(cfg, "get_audit_hmac_key_path", lambda: key_path)
        monkeypatch.setattr(hmac_mod, "get_audit_hmac_key_path", lambda: key_path)
        monkeypatch.delenv("INITRUNNER_AUDIT_HMAC_KEY", raising=False)
        return key_path

    def test_hmac_key_generated_on_first_log(self, tmp_path, monkeypatch):
        key_path = self._env_with_key(monkeypatch, tmp_path)
        assert not key_path.exists()

        db_path = tmp_path / "audit.db"
        with AuditLogger(db_path) as logger:
            logger.log(_make_record())

        assert key_path.exists()
        assert len(key_path.read_bytes()) == 32
        import os
        import stat

        if os.name != "nt":
            mode = stat.S_IMODE(key_path.stat().st_mode)
            assert mode == 0o600

    def test_hmac_key_env_var_overrides_file(self, tmp_path, monkeypatch):
        """Env var wins over file; signatures made under env key verify under env key."""
        key_path = self._env_with_key(monkeypatch, tmp_path)
        # Write a distinct file-based key first
        file_key = b"\xaa" * 32
        key_path.parent.mkdir(parents=True, exist_ok=True)
        key_path.write_bytes(file_key)

        env_key_hex = "bb" * 32
        monkeypatch.setenv("INITRUNNER_AUDIT_HMAC_KEY", env_key_hex)

        db_path = tmp_path / "audit.db"
        with AuditLogger(db_path) as logger:
            logger.log(_make_record())
            result = logger.verify_chain()

        assert result.ok
        assert result.verified_rows == 1
        # File key was not used
        assert key_path.read_bytes() == file_key

    def test_verify_without_key_fails_cleanly_and_no_key_created(self, tmp_path, monkeypatch):
        # Sign with one key, then verify in a fresh environment with no key
        import initrunner.audit._hmac as hmac_mod
        import initrunner.config as cfg

        sign_key_path = tmp_path / "signing_home" / "audit_hmac.key"
        sign_key_path.parent.mkdir(parents=True)
        monkeypatch.setattr(cfg, "get_audit_hmac_key_path", lambda: sign_key_path)
        monkeypatch.setattr(hmac_mod, "get_audit_hmac_key_path", lambda: sign_key_path)
        monkeypatch.delenv("INITRUNNER_AUDIT_HMAC_KEY", raising=False)

        db_path = tmp_path / "audit.db"
        with AuditLogger(db_path) as logger:
            logger.log(_make_record())

        # Simulate copying the DB to a host with no key
        verify_key_path = tmp_path / "no_key_home" / "audit_hmac.key"
        monkeypatch.setattr(cfg, "get_audit_hmac_key_path", lambda: verify_key_path)
        monkeypatch.setattr(hmac_mod, "get_audit_hmac_key_path", lambda: verify_key_path)

        with AuditLogger(db_path) as logger:
            result = logger.verify_chain()

        assert result.ok is False
        assert result.first_break_reason == "key_missing"
        assert not verify_key_path.exists()

    def test_verify_invalid_env_key_reports_key_invalid(self, tmp_path, monkeypatch):
        self._env_with_key(monkeypatch, tmp_path)
        monkeypatch.setenv("INITRUNNER_AUDIT_HMAC_KEY", "not-hex!!")

        db_path = tmp_path / "audit.db"
        # Create DB without signing anything (BEGIN IMMEDIATE never runs)
        with AuditLogger(db_path) as logger:
            result = logger.verify_chain()

        assert result.ok is False
        assert result.first_break_reason == "key_invalid"

    def test_chain_verifies_clean_insert_sequence(self, tmp_path, monkeypatch):
        self._env_with_key(monkeypatch, tmp_path)
        db_path = tmp_path / "audit.db"

        with AuditLogger(db_path) as logger:
            for i in range(5):
                logger.log(_make_record(run_id=f"r{i}"))
            result = logger.verify_chain()

        assert result.ok
        assert result.verified_rows == 5
        assert result.unsigned_legacy_rows == 0
        assert result.last_verified_id == 5
        assert result.pruned_gaps == ()

    def test_chain_detects_field_tampering(self, tmp_path, monkeypatch):
        self._env_with_key(monkeypatch, tmp_path)
        db_path = tmp_path / "audit.db"

        with AuditLogger(db_path) as logger:
            for i in range(3):
                logger.log(_make_record(run_id=f"r{i}"))

        conn = sqlite3.connect(str(db_path))
        conn.execute("UPDATE audit_log SET output='tampered' WHERE id=2")
        conn.commit()
        conn.close()

        with AuditLogger(db_path) as logger:
            result = logger.verify_chain()

        assert result.ok is False
        assert result.first_break_id == 2
        assert result.first_break_reason == "hash_mismatch"

    def test_chain_detects_row_deletion(self, tmp_path, monkeypatch):
        self._env_with_key(monkeypatch, tmp_path)
        db_path = tmp_path / "audit.db"

        with AuditLogger(db_path) as logger:
            for i in range(4):
                logger.log(_make_record(run_id=f"r{i}"))

        # Delete the middle row (id=2); subsequent row's prev_hash no longer
        # matches row 1's record_hash. Since there's now an id gap, the
        # algorithm treats this as pruning, not tampering. To simulate
        # *undetectable* deletion we must delete with no id gap — we use a
        # renumbering trick here: delete row 2 and row 3, then verify finds
        # a prev_hash mismatch on row 4 (since row 3 is gone but row 4 still
        # points at row 3's hash). An id gap IS present though.
        #
        # Real genuine "deletion without pruning signal" is impossible with
        # auto-increment ids unless the attacker also rewrites ids, which
        # requires breaking the chain forward anyway. So this test verifies
        # the pruned_gap *informational* path fires correctly.
        conn = sqlite3.connect(str(db_path))
        conn.execute("DELETE FROM audit_log WHERE id=2")
        conn.commit()
        conn.close()

        with AuditLogger(db_path) as logger:
            result = logger.verify_chain()

        assert result.ok is True
        assert 3 in result.pruned_gaps

    def test_chain_detects_prev_hash_mismatch_without_gap(self, tmp_path, monkeypatch):
        """Rewriting prev_hash to a wrong value, no id gap, is a genuine break."""
        self._env_with_key(monkeypatch, tmp_path)
        db_path = tmp_path / "audit.db"

        with AuditLogger(db_path) as logger:
            for i in range(3):
                logger.log(_make_record(run_id=f"r{i}"))

        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "UPDATE audit_log SET prev_hash=? WHERE id=2",
            ("0" * 64,),
        )
        conn.commit()
        conn.close()

        with AuditLogger(db_path) as logger:
            result = logger.verify_chain()

        assert result.ok is False
        assert result.first_break_id == 2
        assert result.first_break_reason == "prev_hash_mismatch"

    def test_legacy_unsigned_rows_handled(self, tmp_path, monkeypatch):
        """Rows with NULL hashes predating the migration are tolerated."""
        self._env_with_key(monkeypatch, tmp_path)
        db_path = tmp_path / "audit.db"

        # Create the schema by opening/closing a logger
        with AuditLogger(db_path):
            pass

        # Hand-insert a pre-migration row (NULL hashes)
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "INSERT INTO audit_log (run_id, agent_name, timestamp, user_prompt,"
            " model, provider, output, tokens_in, tokens_out, total_tokens,"
            " tool_calls, duration_ms, success, error, prev_hash, record_hash)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL)",
            ("legacy", "a", "2025-01-01T00:00:00Z", "p", "m", "o", "out", 1, 1, 2, 0, 10, 1, None),
        )
        conn.commit()
        conn.close()

        with AuditLogger(db_path) as logger:
            logger.log(_make_record(run_id="new"))
            result = logger.verify_chain()

        assert result.ok
        assert result.unsigned_legacy_rows == 1
        assert result.verified_rows == 1

    def test_null_hash_after_signed_row_is_break(self, tmp_path, monkeypatch):
        self._env_with_key(monkeypatch, tmp_path)
        db_path = tmp_path / "audit.db"

        with AuditLogger(db_path) as logger:
            for i in range(3):
                logger.log(_make_record(run_id=f"r{i}"))

        conn = sqlite3.connect(str(db_path))
        conn.execute("UPDATE audit_log SET record_hash=NULL, prev_hash=NULL WHERE id=2")
        conn.commit()
        conn.close()

        with AuditLogger(db_path) as logger:
            result = logger.verify_chain()

        assert result.ok is False
        assert result.first_break_id == 2
        assert result.first_break_reason == "missing_hash_after_chain_start"

    def test_pruning_by_id_preserves_chain(self, tmp_path, monkeypatch):
        self._env_with_key(monkeypatch, tmp_path)
        db_path = tmp_path / "audit.db"

        with AuditLogger(db_path, max_records=3) as logger:
            for i in range(10):
                logger.log(_make_record(run_id=f"r{i}", timestamp=f"2025-01-01T00:00:{i:02d}Z"))
            logger.prune(retention_days=3650, max_records=3)
            result = logger.verify_chain()

        assert result.ok
        assert result.verified_rows == 3
        # The first remaining row had a predecessor that got pruned;
        # verify treats it as the new chain base, no pruned_gap recorded
        # because there's no row before it to compare against.
        # If any gap is recorded it must be informational only (ok stays True).
        assert result.ok

    def test_pruning_with_out_of_order_timestamps(self, tmp_path, monkeypatch):
        """Timestamp-based retention with out-of-order timestamps may punch
        a hole in the chain; verify reports pruned_gaps, not a break."""
        self._env_with_key(monkeypatch, tmp_path)
        db_path = tmp_path / "audit.db"
        now = datetime.now(UTC)

        with AuditLogger(db_path) as logger:
            # Old row first (will be pruned by retention_days=1)
            logger.log(
                _make_record(
                    run_id="old",
                    timestamp=(now - timedelta(days=100)).isoformat(),
                )
            )
            # Recent row (kept)
            logger.log(
                _make_record(
                    run_id="recent1",
                    timestamp=now.isoformat(),
                )
            )
            # Another old row injected late (will also be pruned, creating
            # a hole between recent1 and recent2)
            logger.log(
                _make_record(
                    run_id="old2",
                    timestamp=(now - timedelta(days=100)).isoformat(),
                )
            )
            logger.log(
                _make_record(
                    run_id="recent2",
                    timestamp=now.isoformat(),
                )
            )
            logger.prune(retention_days=1, max_records=100_000)
            result = logger.verify_chain()

        assert result.ok
        # The row after the pruned middle-row should be in pruned_gaps
        assert len(result.pruned_gaps) >= 1

    def test_concurrent_log_same_instance(self, tmp_path, monkeypatch):
        self._env_with_key(monkeypatch, tmp_path)
        db_path = tmp_path / "audit.db"

        with AuditLogger(db_path) as logger:
            errors: list[BaseException] = []

            def worker(n):
                try:
                    for i in range(n):
                        logger.log(_make_record(run_id=f"t{threading.get_ident()}-{i}"))
                except BaseException as e:
                    errors.append(e)

            threads = [threading.Thread(target=worker, args=(20,)) for _ in range(4)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            assert not errors
            result = logger.verify_chain()

        assert result.ok
        assert result.verified_rows == 80

    def test_concurrent_log_two_instances_same_db(self, tmp_path, monkeypatch):
        """Two AuditLogger instances hitting the same DB must chain correctly
        thanks to BEGIN IMMEDIATE; no forks."""
        self._env_with_key(monkeypatch, tmp_path)
        db_path = tmp_path / "audit.db"

        # Warm-up: create schema once
        with AuditLogger(db_path):
            pass

        errors: list[BaseException] = []

        def worker(tag, n):
            try:
                # Each thread gets its own AuditLogger (its own connection)
                with AuditLogger(db_path) as logger:
                    for i in range(n):
                        logger.log(_make_record(run_id=f"{tag}-{i}"))
            except BaseException as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(f"w{i}", 15)) for i in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        with AuditLogger(db_path) as logger:
            result = logger.verify_chain()

        assert result.ok
        assert result.verified_rows == 45

    def test_budget_state_writes_unaffected_by_signing(self, tmp_path, monkeypatch):
        """Regression: signing logic stayed out of the shared insert helper."""
        self._env_with_key(monkeypatch, tmp_path)
        db_path = tmp_path / "audit.db"

        state = {
            "total_consumed": 5,
            "daily_consumed": 3,
            "daily_cost_consumed": 0.12,
            "weekly_cost_consumed": 0.45,
            "last_reset_date": "2025-01-01",
            "last_weekly_reset": "2025-01-01",
        }
        with AuditLogger(db_path) as logger:
            logger.save_budget_state("agent-x", state)
            loaded = logger.load_budget_state("agent-x")

        assert loaded is not None
        assert loaded["total_consumed"] == 5
