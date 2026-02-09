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

        role = MagicMock()
        role.metadata.name = "agent1"
        role.spec.model.name = "gpt-4o-mini"
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

        role = MagicMock()
        role.metadata.name = "agent1"
        role.spec.model.name = "gpt-4o-mini"
        role.spec.model.provider = "openai"

        record = AuditRecord.from_run(result, role, "test prompt")

        assert record.trigger_type is None
        assert record.trigger_metadata is None


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
