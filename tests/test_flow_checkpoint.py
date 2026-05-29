"""Tests for the audit-backed flow checkpoint journal."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from initrunner.agent.executor_models import ErrorCategory, PendingApproval, RunResult
from initrunner.audit.logger import AuditLogger
from initrunner.flow.checkpoint import (
    CheckpointJournal,
    _envelope_from_dict,
    _envelope_to_dict,
    _result_from_dict,
    _result_to_dict,
)
from initrunner.flow.graph import DelegationEnvelope


@pytest.fixture
def audit_logger():
    tmp = tempfile.mkdtemp()
    log = AuditLogger(Path(tmp) / "audit.db")
    yield log
    log.close()


@pytest.fixture
def journal(audit_logger: AuditLogger) -> CheckpointJournal:
    return CheckpointJournal(audit_logger)


def _envelope(**kw) -> DelegationEnvelope:
    base: dict[str, object] = {
        "prompt": "do the thing",
        "trace": ("entry",),
        "original_prompt": "original",
        "source_service": "entry",
        "one_shot": False,
        "topology_index": 1,
    }
    base.update(kw)
    return DelegationEnvelope(**base)  # type: ignore[invalid-argument-type]


def _result(**kw) -> RunResult:
    base: dict[str, object] = {"run_id": "r1", "output": "answer", "success": True}
    base.update(kw)
    return RunResult(**base)  # type: ignore[invalid-argument-type]


def test_envelope_json_serde() -> None:
    env = _envelope()
    out = _envelope_from_dict(_envelope_to_dict(env))
    assert out == env


def test_result_json_serde_preserves_fields() -> None:
    res = _result(
        tokens_in=5,
        tokens_out=7,
        total_tokens=12,
        error_category=ErrorCategory.TIMEOUT,
        tool_call_names=["search", "http"],
        pending_approvals=[PendingApproval("tc1", "shell", {"cmd": "ls"})],
    )
    out = _result_from_dict(_result_to_dict(res))
    assert out.run_id == "r1"
    assert out.total_tokens == 12
    assert out.error_category is ErrorCategory.TIMEOUT
    assert out.tool_call_names == ["search", "http"]
    assert out.pending_approvals[0].tool_name == "shell"
    assert out.pending_approvals[0].arguments == {"cmd": "ls"}


def test_record_and_replay_roundtrip(journal: CheckpointJournal) -> None:
    env = _envelope()
    res = _result(output="cached output")
    journal.record_completion("flow-1", "writer", 0, env, res, None)

    replay = journal.get_replay("flow-1", "writer")
    assert replay is not None
    assert replay.result.output == "cached output"
    assert replay.envelope.source_service == "entry"
    assert replay.messages is None


def test_completed_services_in_order(journal: CheckpointJournal) -> None:
    journal.record_completion("f", "a", 0, _envelope(), _result(), None)
    journal.record_completion("f", "b", 1, _envelope(), _result(), None)
    journal.record_completion("f", "c", 2, _envelope(), _result(), None)
    assert journal.completed_services("f") == ["a", "b", "c"]


def test_failed_result_not_replayed(journal: CheckpointJournal) -> None:
    journal.record_completion("f", "a", 0, _envelope(), _result(success=False, error="boom"), None)
    # Recorded, but not replayable: resume should re-run.
    assert journal.completed_services("f") == ["a"]
    assert journal.get_replay("f", "a") is None


def test_paused_result_not_replayed(journal: CheckpointJournal) -> None:
    paused = _result(
        status="paused",
        pending_approvals=[PendingApproval("tc", "shell", {})],
    )
    journal.record_completion("f", "a", 0, _envelope(), paused, None)
    assert journal.get_replay("f", "a") is None


def test_replay_missing_returns_none(journal: CheckpointJournal) -> None:
    assert journal.get_replay("nope", "x") is None


def test_prune_scoped_to_flow(journal: CheckpointJournal) -> None:
    journal.record_completion("f1", "a", 0, _envelope(), _result(), None)
    journal.record_completion("f2", "a", 0, _envelope(), _result(), None)
    journal.prune("f1")
    assert journal.completed_services("f1") == []
    assert journal.completed_services("f2") == ["a"]


def test_record_never_raises_on_serialization_failure(audit_logger: AuditLogger) -> None:
    journal = CheckpointJournal(audit_logger)

    # A non-JSON-serializable value on the result must not crash record_completion;
    # the serialize guard logs and returns without writing a checkpoint.
    class _Unserializable:
        pass

    bad = _result()
    bad.output = _Unserializable()  # type: ignore[assignment]
    journal.record_completion("f", "a", 0, _envelope(), bad, None)
    assert journal.completed_services("f") == []


def test_append_checkpoint_swallows_db_errors(audit_logger: AuditLogger) -> None:
    # The audit layer's append_checkpoint never raises (audit.log() contract),
    # even if the underlying connection is broken.
    audit_logger.close()
    audit_logger.append_checkpoint(
        flow_run_id="f",
        service_name="a",
        sequence_number=0,
        envelope_json="{}",
        result_json="{}",
        message_history_json=None,
    )


def test_message_history_roundtrip(journal: CheckpointJournal) -> None:
    pytest.importorskip("pydantic_ai")
    from pydantic_ai.messages import ModelRequest, UserPromptPart

    messages = [ModelRequest(parts=[UserPromptPart(content="hello")])]
    journal.record_completion("f", "a", 0, _envelope(), _result(), messages)
    replay = journal.get_replay("f", "a")
    assert replay is not None
    assert replay.messages is not None
    assert len(replay.messages) == 1


def test_append_checkpoint_signs_with_hmac(audit_logger: AuditLogger) -> None:
    audit_logger.append_checkpoint(
        flow_run_id="f",
        service_name="a",
        sequence_number=0,
        envelope_json="{}",
        result_json="{}",
        message_history_json=None,
    )
    row = audit_logger._conn.execute(
        "SELECT record_hash FROM flow_checkpoints WHERE flow_run_id = ?", ("f",)
    ).fetchone()
    assert row["record_hash"] is not None


def test_upsert_replaces_in_place(audit_logger: AuditLogger) -> None:
    audit_logger.append_checkpoint(
        flow_run_id="f",
        service_name="a",
        sequence_number=0,
        envelope_json='{"v":1}',
        result_json="{}",
        message_history_json=None,
    )
    audit_logger.append_checkpoint(
        flow_run_id="f",
        service_name="a",
        sequence_number=0,
        envelope_json='{"v":2}',
        result_json="{}",
        message_history_json=None,
    )
    assert audit_logger.list_completed_services("f") == ["a"]
    cp = audit_logger.get_checkpoint("f", "a")
    assert cp is not None
    assert cp.envelope_json == '{"v":2}'


def test_checkpoint_writes_do_not_break_main_audit_chain(audit_logger: AuditLogger) -> None:
    from datetime import UTC, datetime

    from initrunner.audit.logger import AuditRecord

    def _record(run_id: str) -> AuditRecord:
        return AuditRecord(
            run_id=run_id,
            agent_name="x",
            timestamp=datetime.now(UTC).isoformat(),
            user_prompt="p",
            model="m",
            provider="pr",
            output="o",
            tokens_in=1,
            tokens_out=1,
            total_tokens=2,
            tool_calls=0,
            duration_ms=1,
            success=True,
        )

    audit_logger.log(_record("r1"))
    audit_logger.append_checkpoint(
        flow_run_id="f",
        service_name="a",
        sequence_number=0,
        envelope_json="{}",
        result_json="{}",
        message_history_json=None,
    )
    audit_logger.log(_record("r2"))

    result = audit_logger.verify_chain()
    assert result.ok is True
    assert result.verified_rows == 2
