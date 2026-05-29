"""Tests for the in-run blackboard shared-state coordination feature.

Covers the Blackboard data structure, the run-scoped blackboard tool, the
fan-in join reading structured entries, end-to-end coordination through a real
flow graph, and audit-chain persistence.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from initrunner.agent.executor import RunResult
from initrunner.agent.schema.base import ApiVersion, Kind, ModelConfig, RoleMetadata
from initrunner.agent.schema.role import AgentSpec, RoleDefinition
from initrunner.agent.schema.tools import BlackboardToolConfig
from initrunner.agent.tools._registry import (
    ToolBuildContext,
    get_builder,
    is_run_scoped,
)
from initrunner.agent.tools.blackboard import build_blackboard_toolset
from initrunner.flow.graph import (
    AgentRef,
    Blackboard,
    BlackboardEntry,
    _build_blackboard_toolsets,
    build_flow_graph,
    run_flow_graph_sync,
)
from initrunner.flow.schema import FlowDefinition

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_role(name: str, *, with_blackboard: bool = False) -> RoleDefinition:
    tools: list = [BlackboardToolConfig()] if with_blackboard else []
    return RoleDefinition(
        apiVersion=ApiVersion.V1,
        kind=Kind.AGENT,
        metadata=RoleMetadata(name=name),
        spec=AgentSpec(
            role=f"You are {name}.",
            model=ModelConfig(provider="openai", name="gpt-5-mini"),
            tools=tools,
        ),
    )


def _build_tool(role: RoleDefinition, board: Blackboard):
    ctx = ToolBuildContext(role=role)
    toolset = build_blackboard_toolset(BlackboardToolConfig(), ctx, board)
    return {name: tool.function for name, tool in toolset.tools.items()}


def _make_flow_data(agents: dict) -> dict:
    return {
        "apiVersion": "initrunner/v1",
        "kind": "Flow",
        "metadata": {"name": "test-flow"},
        "spec": {"agents": agents},
    }


def _make_role_data(name: str, *, blackboard: bool = False) -> dict:
    spec: dict = {
        "role": f"You are {name}.",
        "model": {"provider": "openai", "name": "gpt-5-mini"},
    }
    if blackboard:
        spec["tools"] = [{"type": "blackboard"}]
    return {
        "apiVersion": "initrunner/v1",
        "kind": "Agent",
        "metadata": {"name": name, "description": f"{name} role"},
        "spec": spec,
    }


def _make_run_result(output: str = "done", success: bool = True) -> RunResult:
    r = RunResult(run_id="test-run")
    r.output = output
    r.success = success
    r.duration_ms = 10
    return r


# ---------------------------------------------------------------------------
# Blackboard data structure
# ---------------------------------------------------------------------------


class TestBlackboardStructure:
    def test_post_creates_entry(self):
        board = Blackboard()
        entry_id = board.post("plan", "do the thing", "planner")
        assert len(entry_id) == 8
        entry = board.entries["plan"]
        assert isinstance(entry, BlackboardEntry)
        assert entry.value == "do the thing"
        assert entry.author == "planner"
        assert entry.timestamp.endswith("+00:00")
        assert entry.entry_id == entry_id

    def test_post_duplicate_key_raises(self):
        board = Blackboard()
        board.post("k", "v1", "a")
        with pytest.raises(ValueError, match="already exists"):
            board.post("k", "v2", "b")

    def test_post_exceeds_max_raises(self):
        board = Blackboard(max_entries=2)
        board.post("a", "1", "x")
        board.post("b", "2", "x")
        with pytest.raises(ValueError, match="full"):
            board.post("c", "3", "x")

    def test_read_returns_entry(self):
        board = Blackboard()
        board.post("k", "v", "author")
        out = board.read("k")
        assert out == {
            "key": "k",
            "value": "v",
            "author": "author",
            "timestamp": out["timestamp"],
            "entry_id": out["entry_id"],
        }

    def test_read_missing_key_raises(self):
        board = Blackboard()
        with pytest.raises(ValueError, match="not found"):
            board.read("nope")

    def test_claim_removes_entry(self):
        board = Blackboard()
        board.post("k", "v", "author")
        payload = json.loads(board.claim("k"))
        assert payload["value"] == "v"
        assert "k" not in board.entries
        assert "k" in board.claimed

    def test_claim_twice_raises(self):
        board = Blackboard()
        board.post("k", "v", "author")
        board.claim("k")
        with pytest.raises(ValueError, match="not found"):
            board.claim("k")

    def test_summarize_empty(self):
        assert Blackboard().summarize(80) == "Blackboard is empty."

    def test_summarize_truncates_long_value(self):
        board = Blackboard()
        board.post("k", "x" * 200, "author")
        summary = board.summarize(50)
        assert "[truncated]" in summary
        assert "k (by author)" in summary

    def test_snapshot_shape(self):
        board = Blackboard()
        board.post("keep", "v", "a")
        board.post("gone", "w", "b")
        board.claim("gone")
        snap = board.snapshot()
        assert set(snap["entries"]) == {"keep"}
        assert snap["claimed"] == ["gone"]


# ---------------------------------------------------------------------------
# Tool builder
# ---------------------------------------------------------------------------


class TestBlackboardTool:
    def test_registered_run_scoped(self):
        assert is_run_scoped("blackboard")
        assert get_builder("blackboard") is not None

    def test_post_read_claim_lifecycle(self):
        board = Blackboard()
        tools = _build_tool(_make_role("planner"), board)

        posted = tools["blackboard_post"]("decision", "parallel")
        assert "Posted 'decision'" in posted

        read = json.loads(tools["blackboard_read"]("decision"))
        assert read["value"] == "parallel"
        assert read["author"] == "planner"
        # read leaves the entry in place
        assert "decision" in board.entries

        claimed = json.loads(tools["blackboard_claim"]("decision"))
        assert claimed["value"] == "parallel"
        assert "decision" not in board.entries

    def test_post_applies_config_max_entries(self):
        board = Blackboard()
        ctx = ToolBuildContext(role=_make_role("agent-a"))
        build_blackboard_toolset(BlackboardToolConfig(max_entries=5), ctx, board)
        assert board.max_entries == 5

    def test_post_invalid_key(self):
        board = Blackboard()
        tools = _build_tool(_make_role("agent-a"), board)
        assert "invalid key" in tools["blackboard_post"]("bad key!", "v")
        assert "invalid key" in tools["blackboard_post"]("x" * 65, "v")
        assert board.entries == {}

    def test_post_value_too_large(self):
        board = Blackboard()
        toolset = build_blackboard_toolset(
            BlackboardToolConfig(max_value_chars=10),
            ToolBuildContext(role=_make_role("agent-a")),
            board,
        )
        post = toolset.tools["blackboard_post"].function
        assert "too large" in post("k", "x" * 50)
        assert board.entries == {}

    def test_read_nonexistent_returns_error(self):
        board = Blackboard()
        tools = _build_tool(_make_role("agent-a"), board)
        assert "Error" in tools["blackboard_read"]("missing")

    def test_claim_idempotent_fails_gracefully(self):
        board = Blackboard()
        tools = _build_tool(_make_role("agent-a"), board)
        tools["blackboard_post"]("k", "v")
        tools["blackboard_claim"]("k")
        assert "Error" in tools["blackboard_claim"]("k")

    def test_post_duplicate_returns_error(self):
        board = Blackboard()
        tools = _build_tool(_make_role("agent-a"), board)
        tools["blackboard_post"]("k", "v")
        assert "Error" in tools["blackboard_post"]("k", "v2")

    def test_list_renders_entries(self):
        board = Blackboard()
        tools = _build_tool(_make_role("agent-a"), board)
        assert tools["blackboard_list"]() == "Blackboard is empty."
        tools["blackboard_post"]("k", "v")
        assert "k (by agent-a)" in tools["blackboard_list"]()


# ---------------------------------------------------------------------------
# Step-level toolset wiring
# ---------------------------------------------------------------------------


class TestBlackboardToolsetWiring:
    def test_no_blackboard_tool_builds_nothing(self):
        role = _make_role("plain", with_blackboard=False)
        assert _build_blackboard_toolsets(role, Blackboard()) == []

    def test_blackboard_tool_builds_toolset(self):
        role = _make_role("coord", with_blackboard=True)
        toolsets = _build_blackboard_toolsets(role, Blackboard())
        assert len(toolsets) == 1
        names = set(toolsets[0].tools)
        assert {"blackboard_post", "blackboard_read", "blackboard_claim"} <= names


# ---------------------------------------------------------------------------
# Graph state type
# ---------------------------------------------------------------------------


class TestGraphState:
    def test_build_flow_graph_uses_blackboard_state(self):
        data = _make_flow_data(
            {
                "producer": {
                    "role": "roles/producer.yaml",
                    "sink": {"type": "delegate", "target": "consumer"},
                },
                "consumer": {"role": "roles/consumer.yaml"},
            }
        )
        flow = FlowDefinition.model_validate(data)

        def _ref(name: str) -> AgentRef:
            role = RoleDefinition.model_validate(_make_role_data(name))
            return AgentRef(name=name, role=role, agent=MagicMock(), sink_dispatcher=None)

        refs = {"producer": _ref("producer"), "consumer": _ref("consumer")}
        graph, _entry = build_flow_graph(flow, refs)
        assert graph.state_type is Blackboard


# ---------------------------------------------------------------------------
# End-to-end coordination through the real graph
# ---------------------------------------------------------------------------


class TestFanInReadsBlackboard:
    @patch("initrunner.flow.graph.execute_run_async")
    def test_fan_in_join_reads_upstream_post(self, mock_exec):
        """A diamond where the entry posts a value and the join surfaces it.

        ``entry`` posts ``decision=parallel`` via its blackboard tool. The
        fan-in join feeding ``final`` must fold that structured entry into the
        merged prompt, so ``final`` receives the posted value as attributed
        data, not just concatenated branch text.
        """
        seen_prompts: dict[str, str] = {}

        async def _exec(agent, role, prompt, **kwargs):
            name = role.metadata.name
            seen_prompts[name] = prompt
            if name == "entry":
                tools = {t: tool.function for t, tool in kwargs["extra_toolsets"][0].tools.items()}
                tools["blackboard_post"]("decision", "parallel")
            return _make_run_result(f"output-{name}"), []

        mock_exec.side_effect = _exec

        data = _make_flow_data(
            {
                "entry": {
                    "role": "roles/entry.yaml",
                    "sink": {"type": "delegate", "target": ["svc-a", "svc-b"]},
                    **{"_blackboard": True},
                },
                "svc-a": {
                    "role": "roles/a.yaml",
                    "sink": {"type": "delegate", "target": "final"},
                },
                "svc-b": {
                    "role": "roles/b.yaml",
                    "sink": {"type": "delegate", "target": "final"},
                },
                "final": {"role": "roles/final.yaml"},
            }
        )
        # Strip the marker key we used for readability; entry needs the tool.
        data["spec"]["agents"]["entry"].pop("_blackboard")
        flow = FlowDefinition.model_validate(data)

        from initrunner.flow.orchestrator import FlowAgentConfig, FlowMember

        services = {}
        for name in ["entry", "svc-a", "svc-b", "final"]:
            role = RoleDefinition.model_validate(
                _make_role_data(name, blackboard=(name == "entry"))
            )
            services[name] = FlowMember(
                name=name,
                role=role,
                agent=MagicMock(),
                config=FlowAgentConfig(role=f"roles/{name}.yaml"),
            )

        _refs, _entry, _elapsed, timed_out = run_flow_graph_sync(
            flow,
            services,
            "hello",
            entry_service="entry",
            timeout_seconds=30,
        )

        assert not timed_out
        # final receives the merged prompt with the structured blackboard section
        final_prompt = seen_prompts["final"]
        assert "Shared blackboard" in final_prompt
        assert "decision (by entry): parallel" in final_prompt

    @patch("initrunner.flow.graph.execute_run_async")
    def test_claimed_entry_absent_from_join(self, mock_exec):
        """An entry claimed by a branch agent does not reappear in the join."""

        async def _exec(agent, role, prompt, **kwargs):
            name = role.metadata.name
            extras = kwargs.get("extra_toolsets")
            if extras:
                tools = {t: tool.function for t, tool in extras[0].tools.items()}
                if name == "entry":
                    tools["blackboard_post"]("task", "payload")
                elif name == "svc-a":
                    tools["blackboard_claim"]("task")
            return _make_run_result(f"output-{name}"), []

        mock_exec.side_effect = _exec

        data = _make_flow_data(
            {
                "entry": {
                    "role": "roles/entry.yaml",
                    "sink": {"type": "delegate", "target": ["svc-a", "svc-b"]},
                },
                "svc-a": {
                    "role": "roles/a.yaml",
                    "sink": {"type": "delegate", "target": "final"},
                },
                "svc-b": {
                    "role": "roles/b.yaml",
                    "sink": {"type": "delegate", "target": "final"},
                },
                "final": {"role": "roles/final.yaml"},
            }
        )
        flow = FlowDefinition.model_validate(data)

        from initrunner.flow.orchestrator import FlowAgentConfig, FlowMember

        seen: dict[str, str] = {}

        async def _exec_capture(agent, role, prompt, **kwargs):
            seen[role.metadata.name] = prompt
            return await _exec(agent, role, prompt, **kwargs)

        mock_exec.side_effect = _exec_capture

        services = {}
        for name in ["entry", "svc-a", "svc-b", "final"]:
            role = RoleDefinition.model_validate(
                _make_role_data(name, blackboard=name in ("entry", "svc-a"))
            )
            services[name] = FlowMember(
                name=name,
                role=role,
                agent=MagicMock(),
                config=FlowAgentConfig(role=f"roles/{name}.yaml"),
            )

        run_flow_graph_sync(flow, services, "hello", entry_service="entry", timeout_seconds=30)

        # task was claimed by svc-a, so the final join sees no blackboard section
        assert "task (by entry)" not in seen["final"]


# ---------------------------------------------------------------------------
# Audit persistence
# ---------------------------------------------------------------------------


class TestBlackboardAudit:
    def _logger(self, tmp_path):
        from initrunner.audit.logger import AuditLogger

        return AuditLogger(db_path=tmp_path / "audit.db")

    def test_records_snapshot(self, tmp_path):
        log = self._logger(tmp_path)
        board = Blackboard()
        board.post("k", "v", "planner")
        log.log_blackboard_state(
            flow_run_id="run-1",
            flow_name="my-flow",
            snapshot=board.snapshot(),
        )
        rows = log.query(trigger_type="blackboard_state")
        assert len(rows) == 1
        meta = json.loads(rows[0].trigger_metadata)
        assert meta["flow_name"] == "my-flow"
        assert meta["entries"]["k"]["value"] == "v"
        assert meta["entries"]["k"]["author"] == "planner"

    def test_snapshot_excludes_claimed_value(self, tmp_path):
        log = self._logger(tmp_path)
        board = Blackboard()
        board.post("keep", "v", "a")
        board.post("gone", "w", "b")
        board.claim("gone")
        log.log_blackboard_state(
            flow_run_id="run-2",
            flow_name="f",
            snapshot=board.snapshot(),
        )
        meta = json.loads(log.query(trigger_type="blackboard_state")[0].trigger_metadata)
        assert set(meta["entries"]) == {"keep"}
        assert meta["claimed"] == ["gone"]

    def test_large_value_truncated(self, tmp_path):
        log = self._logger(tmp_path)
        board = Blackboard()
        board.post("big", "x" * 5000, "a")
        log.log_blackboard_state(
            flow_run_id="run-3",
            flow_name="f",
            snapshot=board.snapshot(),
        )
        meta = json.loads(log.query(trigger_type="blackboard_state")[0].trigger_metadata)
        assert "[truncated]" in meta["entries"]["big"]["value"]

    def test_log_blackboard_state_never_raises(self, tmp_path):
        log = self._logger(tmp_path)
        # Force a hard failure by closing the connection so the insert fails,
        # and assert no exception escapes (audit.log must never raise).
        log._conn.close()
        log.log_blackboard_state(
            flow_run_id="run-4",
            flow_name="f",
            snapshot={
                "entries": {"k": {"value": "v", "author": "a", "timestamp": "t"}},
                "claimed": [],
            },
        )

    @patch("initrunner.flow.graph.execute_run_async")
    def test_flow_run_persists_blackboard(self, mock_exec, tmp_path):
        """A flow run with audit logging persists the final board automatically."""

        async def _exec(agent, role, prompt, **kwargs):
            name = role.metadata.name
            extras = kwargs.get("extra_toolsets")
            if extras and name == "producer":
                tools = {t: tool.function for t, tool in extras[0].tools.items()}
                tools["blackboard_post"]("handoff", "ready")
            return _make_run_result(f"output-{name}"), []

        mock_exec.side_effect = _exec

        log = self._logger(tmp_path)
        data = _make_flow_data(
            {
                "producer": {
                    "role": "roles/producer.yaml",
                    "sink": {"type": "delegate", "target": "consumer"},
                },
                "consumer": {"role": "roles/consumer.yaml"},
            }
        )
        flow = FlowDefinition.model_validate(data)

        from initrunner.flow.orchestrator import FlowAgentConfig, FlowMember

        services = {}
        for name in ["producer", "consumer"]:
            role = RoleDefinition.model_validate(
                _make_role_data(name, blackboard=(name == "producer"))
            )
            services[name] = FlowMember(
                name=name,
                role=role,
                agent=MagicMock(),
                config=FlowAgentConfig(role=f"roles/{name}.yaml"),
            )

        run_flow_graph_sync(
            flow,
            services,
            "hello",
            entry_service="producer",
            audit_logger=log,
            flow_run_id="flow-xyz",
            timeout_seconds=30,
        )

        rows = log.query(trigger_type="blackboard_state", limit=10)
        assert len(rows) == 1
        meta = json.loads(rows[0].trigger_metadata)
        assert meta["flow_run_id"] == "flow-xyz"
        assert meta["entries"]["handoff"]["value"] == "ready"
