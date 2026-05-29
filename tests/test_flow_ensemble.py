"""Tests for the ensemble delegate strategy (majority / weighted / judge)."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from initrunner.agent.executor import RunResult
from initrunner.agent.schema.role import RoleDefinition
from initrunner.audit.logger import AuditLogger
from initrunner.eval.judge import VotingResult
from initrunner.flow.graph import (
    AgentRef,
    _compute_topology,
    build_flow_graph,
    run_flow_graph_sync,
)
from initrunner.flow.schema import DelegateSinkConfig, EnsembleConfig, FlowDefinition

_HEX_KEY = "ab" * 32


def _role_data(name: str) -> dict:
    return {
        "apiVersion": "initrunner/v1",
        "kind": "Agent",
        "metadata": {"name": name, "description": name},
        "spec": {"role": f"You are {name}.", "model": {"provider": "openai", "name": "gpt-5-mini"}},
    }


def _ref(name: str) -> AgentRef:
    role = RoleDefinition.model_validate(_role_data(name))
    return AgentRef(name=name, role=role, agent=MagicMock(), sink_dispatcher=None)


def _ensemble_flow(mode: str, ensemble_extra: dict | None = None) -> FlowDefinition:
    ensemble = {"mode": mode}
    if ensemble_extra:
        ensemble.update(ensemble_extra)
    data = {
        "apiVersion": "initrunner/v1",
        "kind": "Flow",
        "metadata": {"name": "ens"},
        "spec": {
            "agents": {
                "router": {
                    "role": "r.yaml",
                    "sink": {
                        "type": "delegate",
                        "target": ["svc-a", "svc-b", "svc-c"],
                        "strategy": "ensemble",
                        "ensemble": ensemble,
                    },
                },
                "svc-a": {"role": "a.yaml"},
                "svc-b": {"role": "b.yaml"},
                "svc-c": {"role": "c.yaml"},
            }
        },
    }
    return FlowDefinition.model_validate(data)


def _services(names: list[str]) -> dict:
    from initrunner.flow.orchestrator import FlowAgentConfig, FlowMember

    services = {}
    for name in names:
        role = RoleDefinition.model_validate(_role_data(name))
        services[name] = FlowMember(
            name=name,
            role=role,
            agent=MagicMock(),
            config=FlowAgentConfig(role=f"{name}.yaml"),
        )
    return services


def _exec_for(outputs: dict[str, str]):
    async def _exec(agent, role, prompt, **kwargs):
        name = role.metadata.name
        return RunResult(run_id=name, output=outputs.get(name, prompt), success=True), []

    return _exec


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------


class TestEnsembleSchema:
    def test_ensemble_strategy_requires_config(self):
        with pytest.raises(ValidationError, match="requires an 'ensemble' config"):
            DelegateSinkConfig(target=["a", "b"], strategy="ensemble")

    def test_ensemble_config_requires_two_targets(self):
        with pytest.raises(ValidationError, match="at least two targets"):
            DelegateSinkConfig(
                target="only", strategy="ensemble", ensemble=EnsembleConfig(mode="majority")
            )

    def test_ensemble_config_only_with_ensemble_strategy(self):
        with pytest.raises(ValidationError, match="only valid with strategy 'ensemble'"):
            DelegateSinkConfig(
                target=["a", "b"], strategy="all", ensemble=EnsembleConfig(mode="majority")
            )

    def test_weighted_requires_weights(self):
        with pytest.raises(ValidationError, match="requires a non-empty 'weights'"):
            EnsembleConfig(mode="weighted")

    def test_weights_must_reference_known_targets(self):
        with pytest.raises(ValidationError, match="unknown targets"):
            DelegateSinkConfig(
                target=["svc-a", "svc-b"],
                strategy="ensemble",
                ensemble=EnsembleConfig(mode="weighted", weights={"ghost": 1.0}),
            )

    def test_weights_cannot_all_be_zero(self):
        with pytest.raises(ValidationError, match="cannot all be zero"):
            EnsembleConfig(mode="weighted", weights={"a": 0.0, "b": 0.0})

    def test_summary_shows_mode(self):
        cfg = DelegateSinkConfig(
            target=["svc-a", "svc-b"],
            strategy="ensemble",
            ensemble=EnsembleConfig(mode="judge"),
        )
        assert cfg.summary() == "delegate: svc-a, svc-b [ensemble:judge]"


# ---------------------------------------------------------------------------
# Topology
# ---------------------------------------------------------------------------


class TestEnsembleTopology:
    def test_compute_topology_extracts_ensemble_config(self):
        flow = _ensemble_flow("majority")
        refs = {n: _ref(n) for n in ["router", "svc-a", "svc-b", "svc-c"]}
        topo = _compute_topology(flow, refs)
        assert "router" in topo.ensemble_configs
        assert topo.ensemble_configs["router"].mode == "majority"
        assert topo.strategies["router"] == "ensemble"

    def test_terminal_ensemble_graph_builds(self):
        flow = _ensemble_flow("majority")
        refs = {n: _ref(n) for n in ["router", "svc-a", "svc-b", "svc-c"]}
        _graph, entry = build_flow_graph(flow, refs)
        assert entry == "router"

    def test_fan_in_ensemble_graph_builds(self):
        data = {
            "apiVersion": "initrunner/v1",
            "kind": "Flow",
            "metadata": {"name": "ens2"},
            "spec": {
                "agents": {
                    "router": {
                        "role": "r.yaml",
                        "sink": {
                            "type": "delegate",
                            "target": ["svc-a", "svc-b"],
                            "strategy": "ensemble",
                            "ensemble": {
                                "mode": "weighted",
                                "weights": {"svc-a": 0.7, "svc-b": 0.3},
                            },
                        },
                    },
                    "svc-a": {"role": "a.yaml", "sink": {"type": "delegate", "target": "final"}},
                    "svc-b": {"role": "b.yaml", "sink": {"type": "delegate", "target": "final"}},
                    "final": {"role": "f.yaml"},
                }
            },
        }
        flow = FlowDefinition.model_validate(data)
        refs = {n: _ref(n) for n in ["router", "svc-a", "svc-b", "final"]}
        _graph, entry = build_flow_graph(flow, refs)
        assert entry == "router"


# ---------------------------------------------------------------------------
# Reducers in a running flow
# ---------------------------------------------------------------------------


class TestEnsembleReducers:
    def test_majority_picks_most_frequent(self):
        flow = _ensemble_flow("majority")
        services = _services(["router", "svc-a", "svc-b", "svc-c"])
        audit = MagicMock()
        outputs = {"svc-a": "Paris", "svc-b": "Paris", "svc-c": "London"}
        with patch("initrunner.flow.graph.execute_run_async", side_effect=_exec_for(outputs)):
            _refs, _entry, _elapsed, timed_out = run_flow_graph_sync(
                flow,
                services,
                "capital?",
                entry_service="router",
                timeout_seconds=30,
                audit_logger=audit,
            )
        assert not timed_out
        call = audit.log_ensemble_vote.call_args
        assert call.kwargs["winning_output"] == "Paris"
        assert call.kwargs["mode"] == "majority"
        assert call.kwargs["vote_trace"]["counts"] == {"Paris": 2, "London": 1}

    def test_weighted_picks_highest_weight_source(self):
        flow = _ensemble_flow("weighted", {"weights": {"svc-a": 0.1, "svc-b": 0.2, "svc-c": 0.9}})
        services = _services(["router", "svc-a", "svc-b", "svc-c"])
        audit = MagicMock()
        outputs = {"svc-a": "A", "svc-b": "B", "svc-c": "C"}
        with patch("initrunner.flow.graph.execute_run_async", side_effect=_exec_for(outputs)):
            run_flow_graph_sync(
                flow,
                services,
                "q",
                entry_service="router",
                timeout_seconds=30,
                audit_logger=audit,
            )
        call = audit.log_ensemble_vote.call_args
        assert call.kwargs["winning_output"] == "C"
        assert call.kwargs["vote_trace"]["winning_source"] == "svc-c"

    def test_judge_picks_winner(self):
        flow = _ensemble_flow("judge", {"judge_criteria": ["clarity"]})
        services = _services(["router", "svc-a", "svc-b", "svc-c"])
        audit = MagicMock()
        outputs = {"svc-a": "long detailed", "svc-b": "mid", "svc-c": "short"}

        def fake_vote(outs, crit, model):
            return VotingResult(
                criteria=["clarity"],
                votes={0: {"clarity": 1}, 1: {"clarity": 0}, 2: {"clarity": 0}},
                winning_index=0,
                consensus_text="c0",
            )

        with (
            patch("initrunner.flow.graph.execute_run_async", side_effect=_exec_for(outputs)),
            patch("initrunner.eval.judge.ensemble_judge_vote_sync", side_effect=fake_vote),
        ):
            run_flow_graph_sync(
                flow,
                services,
                "q",
                entry_service="router",
                timeout_seconds=30,
                audit_logger=audit,
            )
        call = audit.log_ensemble_vote.call_args
        assert call.kwargs["winning_output"] == "long detailed"
        assert call.kwargs["mode"] == "judge"

    def test_empty_candidates_returns_empty_without_raising(self):
        flow = _ensemble_flow("majority")
        services = _services(["router", "svc-a", "svc-b", "svc-c"])
        audit = MagicMock()

        async def _exec(agent, role, prompt, **kwargs):
            name = role.metadata.name
            if name == "router":
                return RunResult(run_id=name, output="go", success=True), []
            # branch agents all fail -> empty prompts
            return RunResult(run_id=name, output="", success=False, error="boom"), []

        with patch("initrunner.flow.graph.execute_run_async", side_effect=_exec):
            _refs, _entry, _elapsed, timed_out = run_flow_graph_sync(
                flow,
                services,
                "q",
                entry_service="router",
                timeout_seconds=30,
                audit_logger=audit,
            )
        assert not timed_out
        # No winner to audit when every candidate is empty.
        assert not audit.log_ensemble_vote.called


# ---------------------------------------------------------------------------
# Audit chain integration
# ---------------------------------------------------------------------------


class TestEnsembleAudit:
    def test_vote_recorded_on_signed_chain(self):
        flow = _ensemble_flow("majority")
        services = _services(["router", "svc-a", "svc-b", "svc-c"])
        outputs = {"svc-a": "X", "svc-b": "X", "svc-c": "Y"}
        prev = os.environ.get("INITRUNNER_AUDIT_HMAC_KEY")
        os.environ["INITRUNNER_AUDIT_HMAC_KEY"] = _HEX_KEY
        try:
            with tempfile.TemporaryDirectory() as td:
                audit = AuditLogger(Path(td) / "audit.db")
                with patch(
                    "initrunner.flow.graph.execute_run_async", side_effect=_exec_for(outputs)
                ):
                    run_flow_graph_sync(
                        flow,
                        services,
                        "q",
                        entry_service="router",
                        timeout_seconds=30,
                        audit_logger=audit,
                    )
                recs = audit.query(trigger_type="ensemble_vote")
                assert len(recs) == 1
                assert recs[0].output == "X"
                assert recs[0].trigger_metadata is not None
                md = json.loads(recs[0].trigger_metadata)
                assert md["mode"] == "majority"
                assert md["vote_trace"]["counts"] == {"X": 2, "Y": 1}
                assert audit.verify_chain().ok
        finally:
            if prev is None:
                os.environ.pop("INITRUNNER_AUDIT_HMAC_KEY", None)
            else:
                os.environ["INITRUNNER_AUDIT_HMAC_KEY"] = prev

    def test_large_output_truncated_in_vote_trace(self):
        flow = _ensemble_flow("majority")
        services = _services(["router", "svc-a", "svc-b", "svc-c"])
        big = "z" * 5000
        outputs = {"svc-a": big, "svc-b": big, "svc-c": "small"}
        prev = os.environ.get("INITRUNNER_AUDIT_HMAC_KEY")
        os.environ["INITRUNNER_AUDIT_HMAC_KEY"] = _HEX_KEY
        try:
            with tempfile.TemporaryDirectory() as td:
                audit = AuditLogger(Path(td) / "audit.db")
                with patch(
                    "initrunner.flow.graph.execute_run_async", side_effect=_exec_for(outputs)
                ):
                    run_flow_graph_sync(
                        flow,
                        services,
                        "q",
                        entry_service="router",
                        timeout_seconds=30,
                        audit_logger=audit,
                    )
                rec = audit.query(trigger_type="ensemble_vote")[0]
                assert rec.trigger_metadata is not None
                md = json.loads(rec.trigger_metadata)
                # candidate strings capped with marker
                assert any("[truncated]" in c for c in md["vote_trace"]["candidates"])
        finally:
            if prev is None:
                os.environ.pop("INITRUNNER_AUDIT_HMAC_KEY", None)
            else:
                os.environ["INITRUNNER_AUDIT_HMAC_KEY"] = prev
