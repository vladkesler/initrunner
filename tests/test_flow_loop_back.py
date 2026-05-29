"""Tests for bounded loop-back edges in flow graphs (critic/refine pattern)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from initrunner.agent.executor import RunResult
from initrunner.agent.schema.role import RoleDefinition
from initrunner.flow.graph import (
    AgentRef,
    DelegationEnvelope,
    _compare,
    _first_number,
    _make_until_predicate,
    build_flow_graph,
    run_flow_graph_sync,
)
from initrunner.flow.orchestrator import FlowAgentConfig, FlowMember
from initrunner.flow.schema import (
    DelegateSinkConfig,
    FlowDefinition,
    FlowSpec,
    LoopBackConfig,
    _parse_until_condition,
)
from initrunner.flow.schema import (
    FlowAgentConfig as SchemaFlowAgentConfig,
)


def _role_data(name: str) -> dict:
    return {
        "apiVersion": "initrunner/v1",
        "kind": "Agent",
        "metadata": {"name": name, "description": f"{name} role"},
        "spec": {
            "role": f"You are {name}.",
            "model": {"provider": "openai", "name": "gpt-5-mini"},
        },
    }


def _make_agent_ref(name: str) -> AgentRef:
    role = RoleDefinition.model_validate(_role_data(name))
    return AgentRef(name=name, role=role, agent=MagicMock(), sink_dispatcher=None)


def _run_result(output: str, success: bool = True) -> RunResult:
    r = RunResult(run_id="test-run")
    r.output = output
    r.success = success
    if not success:
        r.error = "failed"
    return r


def _refine_flow(max_iterations: int = 3, until: dict | None = None) -> FlowDefinition:
    loop_back: dict = {"type": "loop-back", "target": "writer", "max_iterations": max_iterations}
    if until is not None:
        loop_back["until"] = until
    return FlowDefinition.model_validate(
        {
            "apiVersion": "initrunner/v1",
            "kind": "Flow",
            "metadata": {"name": "refine-flow"},
            "spec": {
                "agents": {
                    "writer": {
                        "role": "roles/writer.yaml",
                        "sink": {
                            "type": "delegate",
                            "target": "critic",
                            "loop_back": loop_back,
                        },
                    },
                    "critic": {"role": "roles/critic.yaml"},
                },
            },
        }
    )


def _members(names: list[str]) -> dict[str, FlowMember]:
    return {
        n: FlowMember(
            name=n,
            role=RoleDefinition.model_validate(_role_data(n)),
            agent=MagicMock(),
            config=FlowAgentConfig(role=f"roles/{n}.yaml"),
        )
        for n in names
    }


class TestLoopBackConfigSchema:
    def test_defaults(self):
        cfg = LoopBackConfig(target="writer")
        assert cfg.type == "loop-back"
        assert cfg.max_iterations == 3
        assert cfg.until is None

    def test_max_iterations_upper_bound(self):
        with pytest.raises(ValidationError):
            LoopBackConfig(target="writer", max_iterations=21)

    def test_max_iterations_lower_bound(self):
        with pytest.raises(ValidationError):
            LoopBackConfig(target="writer", max_iterations=0)

    def test_until_contains_valid(self):
        cfg = LoopBackConfig(target="writer", until={"output": "contains:APPROVED"})
        assert cfg.until == {"output": "contains:APPROVED"}

    def test_until_comparison_valid(self):
        cfg = LoopBackConfig(target="writer", until={"output": ">0.8"})
        assert cfg.until == {"output": ">0.8"}

    def test_until_unknown_field_rejected(self):
        with pytest.raises(ValidationError, match="only supports the 'output' field"):
            LoopBackConfig(target="writer", until={"confidence": ">0.8"})

    def test_until_bad_condition_rejected(self):
        with pytest.raises(ValidationError):
            LoopBackConfig(target="writer", until={"output": "not-a-condition"})

    def test_until_non_numeric_comparison_rejected(self):
        with pytest.raises(ValidationError, match="non-numeric"):
            LoopBackConfig(target="writer", until={"output": ">high"})


class TestParseUntilCondition:
    def test_contains(self):
        assert _parse_until_condition("contains:DONE") == ("contains", "DONE")

    def test_contains_strips_whitespace(self):
        assert _parse_until_condition("  contains:  DONE  ") == ("contains", "DONE")

    def test_comparison_operators(self):
        assert _parse_until_condition(">0.8") == ("compare", ">", 0.8)
        assert _parse_until_condition(">=1") == ("compare", ">=", 1.0)
        assert _parse_until_condition("<=2.5") == ("compare", "<=", 2.5)
        assert _parse_until_condition("==3") == ("compare", "==", 3.0)

    def test_empty_contains_rejected(self):
        with pytest.raises(ValueError, match="non-empty"):
            _parse_until_condition("contains:")

    def test_unparseable_rejected(self):
        with pytest.raises(ValueError):
            _parse_until_condition("just text")


class TestUntilPredicate:
    def test_none_when_empty(self):
        assert _make_until_predicate(None) is None
        assert _make_until_predicate({}) is None

    def test_contains_matches(self):
        pred = _make_until_predicate({"output": "contains:APPROVED"})
        assert pred is not None
        assert pred(DelegationEnvelope(prompt="status: APPROVED")) is True
        assert pred(DelegationEnvelope(prompt="needs work")) is False

    def test_contains_case_insensitive(self):
        pred = _make_until_predicate({"output": "contains:approved"})
        assert pred is not None
        assert pred(DelegationEnvelope(prompt="APPROVED")) is True

    def test_numeric_comparison(self):
        pred = _make_until_predicate({"output": ">0.8"})
        assert pred is not None
        assert pred(DelegationEnvelope(prompt="confidence is 0.95 now")) is True
        assert pred(DelegationEnvelope(prompt="confidence is 0.5 now")) is False

    def test_numeric_no_number_does_not_exit(self):
        pred = _make_until_predicate({"output": ">0.8"})
        assert pred is not None
        assert pred(DelegationEnvelope(prompt="no number here")) is False


class TestNumericHelpers:
    def test_first_number(self):
        assert _first_number("score 0.9 done") == 0.9
        assert _first_number("temp -4 units") == -4.0
        assert _first_number("no digits") is None

    def test_compare(self):
        assert _compare(1.0, ">", 0.5) is True
        assert _compare(0.5, ">", 0.5) is False
        assert _compare(0.5, ">=", 0.5) is True
        assert _compare(0.4, "<", 0.5) is True
        assert _compare(0.5, "<=", 0.5) is True
        assert _compare(0.5, "==", 0.5) is True


class TestLoopBackValidation:
    def test_marked_loop_back_allowed(self):
        spec = FlowSpec(
            agents={
                "writer": SchemaFlowAgentConfig(
                    role="roles/writer.yaml",
                    sink=DelegateSinkConfig(
                        target="critic",
                        loop_back=LoopBackConfig(target="writer", max_iterations=3),
                    ),
                ),
                "critic": SchemaFlowAgentConfig(role="roles/critic.yaml"),
            }
        )
        assert spec.agents["writer"].sink is not None
        assert spec.agents["writer"].sink.loop_back is not None

    def test_three_node_refine_loop_allowed(self):
        spec = FlowSpec(
            agents={
                "a": SchemaFlowAgentConfig(role="a.yaml", sink=DelegateSinkConfig(target="b")),
                "b": SchemaFlowAgentConfig(
                    role="b.yaml",
                    sink=DelegateSinkConfig(
                        target="c",
                        loop_back=LoopBackConfig(target="a", max_iterations=4),
                    ),
                ),
                "c": SchemaFlowAgentConfig(role="c.yaml"),
            }
        )
        sink = spec.agents["b"].sink
        assert sink is not None
        assert sink.loop_back is not None
        assert sink.loop_back.target == "a"

    def test_unknown_loop_back_target_rejected(self):
        with pytest.raises(ValidationError, match="loops back to unknown agent"):
            FlowSpec(
                agents={
                    "writer": SchemaFlowAgentConfig(
                        role="w.yaml",
                        sink=DelegateSinkConfig(
                            target="critic",
                            loop_back=LoopBackConfig(target="ghost"),
                        ),
                    ),
                    "critic": SchemaFlowAgentConfig(role="c.yaml"),
                }
            )

    def test_loop_back_to_delegate_target_rejected(self):
        with pytest.raises(ValidationError, match="cannot loop back to its delegate target"):
            FlowSpec(
                agents={
                    "writer": SchemaFlowAgentConfig(
                        role="w.yaml",
                        sink=DelegateSinkConfig(
                            target="critic",
                            loop_back=LoopBackConfig(target="critic"),
                        ),
                    ),
                    "critic": SchemaFlowAgentConfig(role="c.yaml"),
                }
            )

    def test_unmarked_two_node_cycle_still_rejected(self):
        with pytest.raises(ValidationError, match="delegate cycle"):
            FlowSpec(
                agents={
                    "a": SchemaFlowAgentConfig(role="a.yaml", sink=DelegateSinkConfig(target="b")),
                    "b": SchemaFlowAgentConfig(role="b.yaml", sink=DelegateSinkConfig(target="a")),
                }
            )

    def test_unmarked_three_node_cycle_still_rejected(self):
        with pytest.raises(ValidationError, match="delegate cycle"):
            FlowSpec(
                agents={
                    "a": SchemaFlowAgentConfig(role="a.yaml", sink=DelegateSinkConfig(target="b")),
                    "b": SchemaFlowAgentConfig(role="b.yaml", sink=DelegateSinkConfig(target="c")),
                    "c": SchemaFlowAgentConfig(role="c.yaml", sink=DelegateSinkConfig(target="a")),
                }
            )

    def test_loop_back_does_not_mask_unrelated_cycle(self):
        """A valid refine loop must not exempt a separate unmarked cycle."""
        with pytest.raises(ValidationError, match="delegate cycle"):
            FlowSpec(
                agents={
                    "writer": SchemaFlowAgentConfig(
                        role="w.yaml",
                        sink=DelegateSinkConfig(
                            target="critic",
                            loop_back=LoopBackConfig(target="writer"),
                        ),
                    ),
                    "critic": SchemaFlowAgentConfig(role="c.yaml"),
                    "x": SchemaFlowAgentConfig(role="x.yaml", sink=DelegateSinkConfig(target="y")),
                    "y": SchemaFlowAgentConfig(role="y.yaml", sink=DelegateSinkConfig(target="x")),
                }
            )

    def test_summary_shows_loop_back(self):
        sink = DelegateSinkConfig(
            target="critic", loop_back=LoopBackConfig(target="writer", max_iterations=5)
        )
        assert "loop-back: writer x5" in sink.summary()


class TestLoopBackGraphConstruction:
    def test_writer_critic_graph_builds(self):
        flow = _refine_flow()
        refs = {"writer": _make_agent_ref("writer"), "critic": _make_agent_ref("critic")}
        graph, entry = build_flow_graph(flow, refs)
        assert entry == "writer"
        assert graph is not None

    def test_three_node_loop_graph_builds(self):
        flow = FlowDefinition.model_validate(
            {
                "apiVersion": "initrunner/v1",
                "kind": "Flow",
                "metadata": {"name": "three"},
                "spec": {
                    "agents": {
                        "planner": {
                            "role": "planner.yaml",
                            "sink": {"type": "delegate", "target": "writer"},
                        },
                        "writer": {
                            "role": "writer.yaml",
                            "sink": {
                                "type": "delegate",
                                "target": "critic",
                                "loop_back": {
                                    "type": "loop-back",
                                    "target": "planner",
                                    "max_iterations": 2,
                                },
                            },
                        },
                        "critic": {"role": "critic.yaml"},
                    }
                },
            }
        )
        refs = {n: _make_agent_ref(n) for n in ["planner", "writer", "critic"]}
        graph, entry = build_flow_graph(flow, refs)
        assert entry == "planner"
        assert graph is not None


class TestLoopBackExecution:
    @patch("initrunner.flow.graph.execute_run_async")
    def test_loop_terminates_at_max_iterations(self, mock_exec):
        calls: list[str] = []

        async def _exec(agent, role, prompt, **kwargs):
            calls.append(role.metadata.name)
            return _run_result(f"out-{role.metadata.name}"), []

        mock_exec.side_effect = _exec

        flow = _refine_flow(max_iterations=3)
        services = _members(["writer", "critic"])

        _refs, _entry, _elapsed, timed_out = run_flow_graph_sync(
            flow, services, "go", entry_service="writer", timeout_seconds=30
        )

        assert not timed_out
        assert calls.count("writer") == 3
        assert calls.count("critic") == 3

    @patch("initrunner.flow.graph.execute_run_async")
    def test_loop_exits_early_on_until_contains(self, mock_exec):
        calls: list[str] = []

        async def _exec(agent, role, prompt, **kwargs):
            name = role.metadata.name
            calls.append(name)
            if name == "critic":
                # Approve on the second review.
                out = "APPROVED" if calls.count("critic") >= 2 else "needs work"
                return _run_result(out), []
            return _run_result("draft"), []

        mock_exec.side_effect = _exec

        flow = _refine_flow(max_iterations=5, until={"output": "contains:APPROVED"})
        services = _members(["writer", "critic"])

        _refs, _entry, _elapsed, timed_out = run_flow_graph_sync(
            flow, services, "go", entry_service="writer", timeout_seconds=30
        )

        assert not timed_out
        # Exited after the second round, well before max_iterations=5.
        assert calls.count("critic") == 2
        assert calls.count("writer") == 2

    @patch("initrunner.flow.graph.execute_run_async")
    def test_loop_exits_early_on_numeric_until(self, mock_exec):
        calls: list[str] = []

        async def _exec(agent, role, prompt, **kwargs):
            name = role.metadata.name
            calls.append(name)
            if name == "critic":
                score = "0.95" if calls.count("critic") >= 3 else "0.5"
                return _run_result(f"confidence {score}"), []
            return _run_result("draft"), []

        mock_exec.side_effect = _exec

        flow = _refine_flow(max_iterations=5, until={"output": ">0.8"})
        services = _members(["writer", "critic"])

        run_flow_graph_sync(flow, services, "go", entry_service="writer", timeout_seconds=30)

        assert calls.count("critic") == 3
