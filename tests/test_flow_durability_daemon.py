"""Daemon-path durability regression tests for resume-after-failure.

These drive the *same* daemon code path the CLI ``initrunner flow up`` uses:
``start_daemon`` -> ``_daemon_main`` -> the per-run ``_run_graph`` closure that
runs the flow graph and decides whether to prune the durable checkpoint journal.

The bug this guards against: ``_run_graph`` pruned the journal after any
``graph.run()`` that did not raise a Python exception. A sub-agent returning
``RunResult(success=False)`` is not an exception, so the run returned normally,
the journal was pruned, and ``initrunner flow resume <id>`` then found zero
checkpointed services. The fix gates the prune on the run having fully
succeeded, mirroring the orchestrator's success-gated prune.

Agents are mocked (no model calls). The trigger dispatcher is replaced with a
capture shim so a single ``_RunRequest`` can be injected through the real
``on_trigger`` ingress, exactly as a live cron/webhook trigger would.
"""

from __future__ import annotations

import tempfile
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import anyio
import pytest

from initrunner.agent.executor_models import RunResult
from initrunner.audit.logger import AuditLogger
from initrunner.flow.checkpoint import CheckpointJournal
from initrunner.flow.orchestrator import FlowMember
from initrunner.flow.schema import (
    DelegateSinkConfig,
    DurabilityConfig,
    FlowAgentConfig,
    FlowDefinition,
    FlowMetadata,
    FlowSpec,
)

_FIXED_RUN_ID = "daemon-run-fixed"


@pytest.fixture
def audit_logger():
    # The audit DB lives under a freshly-created /tmp subdir, never /tmp itself.
    tmp = tempfile.mkdtemp(prefix="ir-daemon-durability-")
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
    # The entry agent carries a (truthy) trigger list so _daemon_main wires a
    # TriggerDispatcher for it; the dispatcher itself is the capture shim below.
    role.spec.triggers = [SimpleNamespace(type="manual")] if name == "a" else None
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
        metadata=FlowMetadata(name="durable-daemon-test"),
        spec=FlowSpec(agents=agents, durability=DurabilityConfig(enabled=True)),
    )


def _make_members(flow: FlowDefinition, audit_logger: AuditLogger) -> dict[str, FlowMember]:
    members: dict[str, FlowMember] = {}
    for name, config in flow.spec.agents.items():
        members[name] = FlowMember(
            name=name,
            role=_make_role(name),
            agent=MagicMock(),
            config=config,
            audit_logger=audit_logger,
        )
    return members


def _make_capture_dispatcher(captured: list):
    """Build a TriggerDispatcher stand-in that records the on_trigger callback.

    ``_daemon_main`` constructs one per service that declares triggers, passing
    ``(trigger_configs, partial(on_trigger, service_name))``. The shim records
    the callback into ``captured`` so the test can fire it like a real trigger
    would, and makes ``start_all``/``stop_all`` no-ops so no trigger threads
    spin up.
    """

    class _CaptureDispatcher:
        def __init__(self, trigger_configs, callback) -> None:
            captured.append(callback)

        def start_all(self) -> None:
            pass

        def stop_all(self) -> None:
            pass

    return _CaptureDispatcher


def _run_daemon_until_complete(
    flow: FlowDefinition,
    members: dict[str, FlowMember],
    audit_logger: AuditLogger,
    *,
    completed: threading.Event,
) -> None:
    """Drive _daemon_main: inject one trigger, wait for the run, then shut down.

    This exercises the real start_daemon -> _daemon_main -> _run_graph path.
    """
    captured: list = []
    shutdown = threading.Event()

    async def _drive() -> None:
        # Run the actual daemon loop concurrently with the test driver.
        async with anyio.create_task_group() as tg:
            tg.start_soon(_daemon_run, flow, members, audit_logger, shutdown)
            # Wait until _daemon_main has wired the capture dispatcher, then fire.
            for _ in range(200):
                if captured:
                    break
                await anyio.sleep(0.01)
            assert captured, "daemon never wired a trigger dispatcher"
            on_trigger = captured[0]
            on_trigger(SimpleNamespace(prompt="kickoff"))
            # Wait for the graph run (including the post-run prune decision).
            for _ in range(500):
                if completed.is_set():
                    break
                await anyio.sleep(0.01)
            # Give _run_graph a moment to finish its prune decision after the
            # terminal agent returns, then stop the daemon.
            await anyio.sleep(0.05)
            shutdown.set()

    with patch("initrunner._ids.generate_id", return_value=_FIXED_RUN_ID):
        with patch(
            "initrunner.triggers.dispatcher.TriggerDispatcher",
            _make_capture_dispatcher(captured),
        ):
            anyio.run(_drive)


async def _daemon_run(flow, members, audit_logger, shutdown) -> None:
    from initrunner.flow.graph import _daemon_main

    await _daemon_main(flow, members, audit_logger, shutdown)


def test_daemon_failed_run_keeps_checkpoints(audit_logger: AuditLogger) -> None:
    """A failing sub-agent must leave completed checkpoints intact for resume."""
    flow = _durable_flow()
    members = _make_members(flow, audit_logger)
    completed = threading.Event()
    pruned: list[str] = []

    async def _exec(agent, role, prompt, **kwargs):
        name = role.metadata.name
        if name == "a":
            return RunResult(run_id="a-run", output="A output", success=True), []
        # b is terminal and "crashes" by returning a failed result (no raise).
        completed.set()
        return RunResult(run_id="b-run", output="", success=False, error="boom"), []

    real_prune = CheckpointJournal.prune

    def _tracking_prune(self, flow_run_id: str) -> None:
        pruned.append(flow_run_id)
        real_prune(self, flow_run_id)

    with patch("initrunner.flow.graph.execute_run_async", side_effect=_exec):
        with patch.object(CheckpointJournal, "prune", _tracking_prune):
            _run_daemon_until_complete(flow, members, audit_logger, completed=completed)

    # The failing run must NOT prune, so both checkpoints survive.
    assert pruned == [], f"journal was pruned on a failed run: {pruned}"
    surviving = audit_logger.list_completed_services(_FIXED_RUN_ID)
    assert surviving == ["a", "b"], surviving

    # And resume-after-failure can see the completed work: 'a' replays, 'b' re-runs.
    journal = CheckpointJournal(audit_logger)
    assert journal.get_replay(_FIXED_RUN_ID, "a") is not None, "succeeded 'a' is replayable"
    assert journal.get_replay(_FIXED_RUN_ID, "b") is None, "failed 'b' is not replayable"


def test_daemon_successful_run_prunes_checkpoints(audit_logger: AuditLogger) -> None:
    """A fully successful daemon run still prunes its journal."""
    flow = _durable_flow()
    members = _make_members(flow, audit_logger)
    completed = threading.Event()
    pruned: list[str] = []

    async def _exec(agent, role, prompt, **kwargs):
        name = role.metadata.name
        if name == "b":
            completed.set()
        return RunResult(run_id=f"{name}-run", output=f"{name} out", success=True), []

    real_prune = CheckpointJournal.prune

    def _tracking_prune(self, flow_run_id: str) -> None:
        pruned.append(flow_run_id)
        real_prune(self, flow_run_id)

    with patch("initrunner.flow.graph.execute_run_async", side_effect=_exec):
        with patch.object(CheckpointJournal, "prune", _tracking_prune):
            _run_daemon_until_complete(flow, members, audit_logger, completed=completed)

    assert pruned == [_FIXED_RUN_ID], f"successful run should prune exactly once: {pruned}"
    assert audit_logger.list_completed_services(_FIXED_RUN_ID) == []
