"""Crash-and-resume integration tests for durable flows.

Drives FlowOrchestrator with a real audit-backed checkpoint journal and
mocked agents to prove that a flow interrupted mid-execution replays the
completed sub-agent envelopes on resume instead of re-running them.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from initrunner.agent.executor_models import RunResult
from initrunner.audit.logger import AuditLogger
from initrunner.flow.orchestrator import FlowMember, FlowOrchestrator
from initrunner.flow.schema import (
    DelegateSinkConfig,
    DurabilityConfig,
    FlowAgentConfig,
    FlowDefinition,
    FlowMetadata,
    FlowSpec,
)


@pytest.fixture
def audit_logger():
    tmp = tempfile.mkdtemp()
    log = AuditLogger(Path(tmp) / "audit.db")
    yield log
    log.close()


def _make_role(name: str) -> MagicMock:
    role = MagicMock()
    role.metadata.name = name
    role.metadata.description = f"{name} agent"
    role.metadata.tags = []
    role.metadata.can_delegate_to = None
    role.spec.memory = None
    role.spec.sinks = []
    role.spec.triggers = None
    return role


def _durable_flow() -> FlowDefinition:
    # a -> b chain, durability enabled.
    agents = {
        "a": FlowAgentConfig(role="a.yaml", sink=DelegateSinkConfig(target="b")),
        "b": FlowAgentConfig(role="b.yaml"),
    }
    return FlowDefinition(
        apiVersion="initrunner.dev/v1",
        kind="Flow",
        metadata=FlowMetadata(name="durable-test"),
        spec=FlowSpec(agents=agents, durability=DurabilityConfig(enabled=True)),
    )


def _install_members(orch: FlowOrchestrator) -> None:
    """Replace _build_members with a no-op that injects mocked FlowMembers."""
    flow = orch._flow

    def _fake_build(*, one_shot: bool = False) -> None:
        for name, config in flow.spec.agents.items():
            orch._members[name] = FlowMember(
                name=name,
                role=_make_role(name),
                agent=MagicMock(),
                config=config,
                audit_logger=orch._audit_logger,
            )

    orch._build_members = _fake_build  # type: ignore[method-assign]


def test_resume_replays_completed_and_reruns_rest(audit_logger: AuditLogger) -> None:
    flow = _durable_flow()
    base = Path(tempfile.mkdtemp())

    # Record which services execute, per run, to prove replay vs re-run.
    # The graph may execute the entry node more than once within a single run,
    # so we assert on the resume *delta* (which services ran at all on resume),
    # not on absolute per-service counts. entry_service is pinned for a
    # deterministic a -> b order regardless of hash-randomized entry detection.
    ran_run1: list[str] = []
    ran_run2: list[str] = []

    def _make_side_effect(sink: list[str], *, b_succeeds: bool):
        async def _run(agent, role, prompt, **kwargs):
            name = role.metadata.name
            sink.append(name)
            if name == "a":
                return RunResult(run_id="a-run", output="A output", success=True), []
            # b "crashes" on the first run by returning a failed result, then
            # succeeds when re-run on resume.
            if not b_succeeds:
                return (
                    RunResult(run_id="b-run", output="", success=False, error="boom"),
                    [],
                )
            return RunResult(run_id="b-run2", output="B output", success=True), []

        return _run

    with patch(
        "initrunner.flow.graph.execute_run_async",
        side_effect=_make_side_effect(ran_run1, b_succeeds=False),
    ):
        orch1 = FlowOrchestrator(flow, base, audit_logger=audit_logger)
        _install_members(orch1)
        result1 = orch1.run_once("start", entry_service="a")
    flow_run_id = result1.flow_run_id

    # First run: a succeeded (replayable checkpoint); b ran and failed, so it is
    # checkpointed too but its recorded result is not replayable.
    assert result1.success is False
    assert audit_logger.list_completed_services(flow_run_id) == ["a", "b"]
    from initrunner.flow.checkpoint import CheckpointJournal

    journal = CheckpointJournal(audit_logger)
    assert journal.get_replay(flow_run_id, "a") is not None, "succeeded 'a' is replayable"
    assert journal.get_replay(flow_run_id, "b") is None, "failed 'b' is not replayable"
    assert "a" in ran_run1 and "b" in ran_run1

    # Resume: a is replayed from the journal (must NOT execute), b is re-run.
    with patch(
        "initrunner.flow.graph.execute_run_async",
        side_effect=_make_side_effect(ran_run2, b_succeeds=True),
    ):
        orch2 = FlowOrchestrator(flow, base, audit_logger=audit_logger)
        _install_members(orch2)
        result2 = orch2.resume(flow_run_id, "start", entry_service="a")

    assert "a" not in ran_run2, "completed service 'a' must be replayed, not re-run"
    assert "b" in ran_run2, "failed service 'b' must be re-run on resume"
    assert result2.success is True
    assert "B output" in result2.output


def test_successful_run_prunes_checkpoints(audit_logger: AuditLogger) -> None:
    flow = _durable_flow()
    base = Path(tempfile.mkdtemp())

    async def _all_succeed(agent, role, prompt, **kwargs):
        name = role.metadata.name
        return RunResult(run_id=f"{name}-run", output=f"{name} out", success=True), []

    with patch("initrunner.flow.graph.execute_run_async", side_effect=_all_succeed):
        orch = FlowOrchestrator(flow, base, audit_logger=audit_logger)
        _install_members(orch)
        result = orch.run_once("go", entry_service="a")

    assert result.success is True
    # A clean, successful run prunes its journal.
    assert audit_logger.list_completed_services(result.flow_run_id) == []


def test_non_durable_flow_writes_no_checkpoints(audit_logger: AuditLogger) -> None:
    agents = {
        "a": FlowAgentConfig(role="a.yaml", sink=DelegateSinkConfig(target="b")),
        "b": FlowAgentConfig(role="b.yaml"),
    }
    flow = FlowDefinition(
        apiVersion="initrunner.dev/v1",
        kind="Flow",
        metadata=FlowMetadata(name="plain"),
        spec=FlowSpec(agents=agents),  # durability disabled by default
    )
    base = Path(tempfile.mkdtemp())

    async def _all_succeed(agent, role, prompt, **kwargs):
        name = role.metadata.name
        return RunResult(run_id=f"{name}-run", output=f"{name} out", success=True), []

    with patch("initrunner.flow.graph.execute_run_async", side_effect=_all_succeed):
        orch = FlowOrchestrator(flow, base, audit_logger=audit_logger)
        _install_members(orch)
        result = orch.run_once("go", entry_service="a")

    assert result.success is True
    assert audit_logger.list_completed_services(result.flow_run_id) == []


def test_resume_requires_durability(audit_logger: AuditLogger) -> None:
    agents = {"a": FlowAgentConfig(role="a.yaml")}
    flow = FlowDefinition(
        apiVersion="initrunner.dev/v1",
        kind="Flow",
        metadata=FlowMetadata(name="plain"),
        spec=FlowSpec(agents=agents),
    )
    orch = FlowOrchestrator(flow, Path("."), audit_logger=audit_logger)
    with pytest.raises(ValueError, match="durability"):
        orch.resume("some-id")


def test_resume_requires_audit_logger() -> None:
    flow = _durable_flow()
    orch = FlowOrchestrator(flow, Path("."), audit_logger=None)
    with pytest.raises(ValueError, match="audit logger"):
        orch.resume("some-id")
