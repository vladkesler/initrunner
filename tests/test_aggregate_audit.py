"""Tests for compose/team aggregate audit logging and exclusion filter."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from initrunner.audit.logger import AuditLogger, AuditRecord

# ---------------------------------------------------------------------------
# Audit exclusion filter
# ---------------------------------------------------------------------------


class TestExcludeTriggerTypes:
    """AuditLogger.query() exclude_trigger_types parameter."""

    def _make_logger(self, tmp_path: Path) -> AuditLogger:
        return AuditLogger(tmp_path / "test.db")

    def _log_record(self, logger: AuditLogger, **overrides) -> None:
        defaults = dict(
            run_id="r1",
            agent_name="a",
            timestamp="2026-04-01T00:00:00",
            user_prompt="p",
            model="m",
            provider="pr",
            output="o",
            tokens_in=1,
            tokens_out=1,
            total_tokens=2,
            tool_calls=0,
            duration_ms=100,
            success=True,
        )
        defaults.update(overrides)
        logger.log(AuditRecord(**defaults))

    def test_no_exclusion_returns_all(self, tmp_path):
        logger = self._make_logger(tmp_path)
        self._log_record(logger, run_id="r1", trigger_type=None)
        self._log_record(logger, run_id="r2", trigger_type="compose")
        self._log_record(logger, run_id="r3", trigger_type="compose_run")

        results = logger.query(limit=100)
        assert len(results) == 3

    def test_exclude_compose_delegate_team(self, tmp_path):
        logger = self._make_logger(tmp_path)
        self._log_record(logger, run_id="r1", trigger_type=None, agent_name="agent1")
        self._log_record(logger, run_id="r2", trigger_type="compose", agent_name="svc1")
        self._log_record(logger, run_id="r3", trigger_type="delegate", agent_name="svc2")
        self._log_record(logger, run_id="r4", trigger_type="team", agent_name="persona1")
        self._log_record(logger, run_id="r5", trigger_type="compose_run", agent_name="my-compose")
        self._log_record(logger, run_id="r6", trigger_type="team_run", agent_name="my-team")

        results = logger.query(
            limit=100,
            exclude_trigger_types=["compose", "delegate", "team"],
        )
        run_ids = {r.run_id for r in results}
        # Should include: null trigger, compose_run, team_run
        assert "r1" in run_ids
        assert "r5" in run_ids
        assert "r6" in run_ids
        # Should exclude: compose, delegate, team
        assert "r2" not in run_ids
        assert "r3" not in run_ids
        assert "r4" not in run_ids

    def test_exclusion_applied_before_limit(self, tmp_path):
        logger = self._make_logger(tmp_path)
        # Log 5 internal rows then 2 top-level
        for i in range(5):
            self._log_record(
                logger,
                run_id=f"internal-{i}",
                trigger_type="compose",
                timestamp=f"2026-04-01T00:00:{i:02d}",
            )
        self._log_record(
            logger, run_id="top1", trigger_type="compose_run", timestamp="2026-04-01T00:01:00"
        )
        self._log_record(
            logger, run_id="top2", trigger_type=None, timestamp="2026-04-01T00:02:00"
        )

        results = logger.query(limit=2, exclude_trigger_types=["compose"])
        assert len(results) == 2
        run_ids = {r.run_id for r in results}
        assert run_ids == {"top1", "top2"}


# ---------------------------------------------------------------------------
# Compose aggregate audit row
# ---------------------------------------------------------------------------


class TestComposeAggregateAudit:
    """ComposeOrchestrator.run_once() logs an aggregate audit row."""

    def test_aggregate_row_logged(self, tmp_path):
        from initrunner.compose.orchestrator import ComposeRunResult, ServiceStepResult

        audit_logger = MagicMock()
        orch = MagicMock()
        orch._audit_logger = audit_logger
        orch._compose = MagicMock()
        orch._compose.metadata.name = "test-compose"

        from initrunner.compose.orchestrator import ComposeOrchestrator

        result = ComposeRunResult(
            output="done",
            output_mode="single",
            final_service_name="consumer",
            compose_run_id="cid-123",
            steps=[
                ServiceStepResult(
                    service_name="producer",
                    tokens_in=10,
                    tokens_out=5,
                    duration_ms=100,
                    tool_calls=2,
                ),
                ServiceStepResult(
                    service_name="consumer",
                    tokens_in=20,
                    tokens_out=10,
                    duration_ms=200,
                    tool_calls=1,
                ),
            ],
            total_tokens_in=30,
            total_tokens_out=15,
            total_duration_ms=300,
            success=True,
        )

        # Call the _log_aggregate method directly
        ComposeOrchestrator._log_aggregate(orch, "cid-123", "test prompt", result)

        audit_logger.log.assert_called_once()
        record = audit_logger.log.call_args[0][0]
        assert record.run_id == "cid-123"
        assert record.agent_name == "test-compose"
        assert record.trigger_type == "compose_run"
        assert record.model == "multi"
        assert record.provider == "multi"
        assert record.tokens_in == 30
        assert record.tokens_out == 15
        assert record.total_tokens == 45
        assert record.tool_calls == 3
        assert record.success is True

        metadata = json.loads(record.trigger_metadata)
        assert metadata["scope"] == "aggregate"
        assert metadata["compose_run_id"] == "cid-123"
        assert metadata["compose_name"] == "test-compose"

    def test_no_audit_logger_skips(self):
        from initrunner.compose.orchestrator import ComposeOrchestrator, ComposeRunResult

        orch = MagicMock()
        orch._audit_logger = None

        result = ComposeRunResult(output="", output_mode="none", final_service_name=None)
        # Should not raise
        ComposeOrchestrator._log_aggregate(orch, "cid", "prompt", result)


# ---------------------------------------------------------------------------
# Team aggregate audit row
# ---------------------------------------------------------------------------


class TestTeamAggregateAudit:
    """_log_team_aggregate() logs an aggregate audit row."""

    def test_aggregate_row_logged(self):
        from initrunner.team.graph import _log_team_aggregate
        from initrunner.team.results import TeamResult

        audit_logger = MagicMock()
        team = MagicMock()
        team.metadata.name = "review-team"
        team.spec.model.name = "gpt-5-mini"
        team.spec.model.provider = "openai"
        team.spec.personas = {"reviewer": MagicMock(model=None), "editor": MagicMock(model=None)}

        result = TeamResult(
            team_run_id="tid-456",
            team_name="review-team",
            final_output="final result",
            total_tokens_in=50,
            total_tokens_out=25,
            total_tokens=75,
            total_tool_calls=5,
            total_duration_ms=500,
            success=True,
        )

        _log_team_aggregate(audit_logger, team, "review this code", result)

        audit_logger.log.assert_called_once()
        record = audit_logger.log.call_args[0][0]
        assert record.run_id == "tid-456"
        assert record.agent_name == "review-team"
        assert record.trigger_type == "team_run"
        assert record.model == "gpt-5-mini"
        assert record.provider == "openai"
        assert record.total_tokens == 75

        metadata = json.loads(record.trigger_metadata)
        assert metadata["scope"] == "aggregate"
        assert metadata["team_run_id"] == "tid-456"

    def test_persona_overrides_use_multi(self):
        from initrunner.team.graph import _log_team_aggregate
        from initrunner.team.results import TeamResult

        audit_logger = MagicMock()
        team = MagicMock()
        team.metadata.name = "mixed-team"
        team.spec.model.name = "gpt-5-mini"
        team.spec.model.provider = "openai"
        # One persona has a model override
        team.spec.personas = {
            "p1": MagicMock(model=None),
            "p2": MagicMock(model=MagicMock(name="claude-sonnet-4-6")),
        }

        result = TeamResult(team_run_id="tid", team_name="mixed-team")
        _log_team_aggregate(audit_logger, team, "task", result)

        record = audit_logger.log.call_args[0][0]
        assert record.model == "multi"
        assert record.provider == "multi"

    def test_no_audit_logger_skips(self):
        from initrunner.team.graph import _log_team_aggregate
        from initrunner.team.results import TeamResult

        result = TeamResult(team_run_id="tid", team_name="t")
        # Should not raise
        _log_team_aggregate(None, MagicMock(), "task", result)


# ---------------------------------------------------------------------------
# Dashboard route audit_logger wiring
# ---------------------------------------------------------------------------


class TestDashboardAuditWiring:
    """Dashboard compose/team stream routes pass audit_logger."""

    def test_compose_stream_passes_audit_logger(self):
        with (
            patch("initrunner.dashboard.routers.runs._audit_logger") as mock_al,
            patch("initrunner.dashboard.streaming.stream_compose_run_sse") as mock_stream,
        ):
            mock_al.return_value = MagicMock()
            mock_stream.return_value = iter([])

            from importlib import import_module

            mod = import_module("initrunner.dashboard.routers.compose")
            # Verify that stream_compose_run_sse is called with audit_logger kwarg
            # by checking the source -- the actual endpoint requires full ASGI setup
            import inspect

            source = inspect.getsource(mod.stream_compose_run)
            assert "audit_logger=" in source

    def test_team_stream_passes_audit_logger(self):
        import inspect
        from importlib import import_module

        mod = import_module("initrunner.dashboard.routers.teams")
        source = inspect.getsource(mod.stream_team_run)
        assert "audit_logger=" in source
