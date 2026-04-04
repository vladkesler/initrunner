"""Tests for the flow orchestrator (graph-based)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from initrunner.flow.orchestrator import (
    FlowMember,
    FlowOrchestrator,
    apply_shared_memory,
)
from initrunner.flow.schema import (
    FlowAgentConfig,
    FlowDefinition,
)


def _make_role_data() -> dict:
    return {
        "apiVersion": "initrunner/v1",
        "kind": "Agent",
        "metadata": {"name": "test-agent", "description": "test"},
        "spec": {
            "role": "You are a test agent.",
            "model": {"provider": "openai", "name": "gpt-5-mini"},
        },
    }


def _make_flow_data(agents: dict | None = None) -> dict:
    if agents is None:
        agents = {
            "producer": {
                "role": "roles/producer.yaml",
                "sink": {"type": "delegate", "target": "consumer"},
            },
            "consumer": {"role": "roles/consumer.yaml"},
        }
    return {
        "apiVersion": "initrunner/v1",
        "kind": "Flow",
        "metadata": {"name": "test-flow"},
        "spec": {"agents": agents},
    }


class TestFlowMember:
    def test_creation(self):
        from initrunner.agent.schema.role import RoleDefinition

        role = RoleDefinition.model_validate(_make_role_data())
        agent = MagicMock()

        svc = FlowMember(
            name="test",
            role=role,
            agent=agent,
            config=FlowAgentConfig(role="test.yaml"),
        )

        assert svc.name == "test"
        assert svc.run_count == 0
        assert svc.error_count == 0
        assert svc.is_alive

    def test_add_sink(self):
        from initrunner.agent.schema.role import RoleDefinition

        role = RoleDefinition.model_validate(_make_role_data())
        agent = MagicMock()

        svc = FlowMember(
            name="test",
            role=role,
            agent=agent,
            config=FlowAgentConfig(role="test.yaml"),
        )

        mock_sink = MagicMock()
        svc.add_sink(mock_sink)
        assert svc._sink_dispatcher.count == 1


class TestFlowOrchestrator:
    def test_topological_order_no_deps(self):
        flow = FlowDefinition.model_validate(
            _make_flow_data(
                {
                    "svc-a": {"role": "a.yaml"},
                    "svc-b": {"role": "b.yaml"},
                    "svc-c": {"role": "c.yaml"},
                }
            )
        )
        orch = FlowOrchestrator(flow, Path("."))
        for name in flow.spec.agents:
            orch._members[name] = MagicMock()

        tiers = orch._topological_order()
        assert len(tiers) == 1
        assert sorted(tiers[0]) == ["svc-a", "svc-b", "svc-c"]

    def test_topological_order_with_deps(self):
        flow = FlowDefinition.model_validate(
            _make_flow_data(
                {
                    "svc-a": {"role": "a.yaml"},
                    "svc-b": {"role": "b.yaml", "needs": ["svc-a"]},
                    "svc-c": {"role": "c.yaml", "needs": ["svc-b"]},
                }
            )
        )
        orch = FlowOrchestrator(flow, Path("."))
        for name in flow.spec.agents:
            orch._members[name] = MagicMock()

        tiers = orch._topological_order()
        assert len(tiers) == 3
        assert tiers[0] == ["svc-a"]
        assert tiers[1] == ["svc-b"]
        assert tiers[2] == ["svc-c"]

    @patch("initrunner.flow.orchestrator.load_and_build")
    def test_build_services(self, mock_load):
        from initrunner.agent.schema.role import RoleDefinition

        role = RoleDefinition.model_validate(_make_role_data())
        mock_load.return_value = (role, MagicMock())

        flow = FlowDefinition.model_validate(_make_flow_data())
        orch = FlowOrchestrator(flow, Path("."))
        orch._build_members()

        assert "producer" in orch._members
        assert "consumer" in orch._members
        assert mock_load.call_count == 2

    @patch("initrunner.flow.orchestrator.load_and_build")
    def test_find_entry(self, mock_load):
        from initrunner.agent.schema.role import RoleDefinition

        role = RoleDefinition.model_validate(_make_role_data())
        mock_load.return_value = (role, MagicMock())

        flow = FlowDefinition.model_validate(_make_flow_data())
        orch = FlowOrchestrator(flow, Path("."))
        orch._build_members()

        entry = orch._find_entry()
        assert entry.name == "producer"

    @patch("initrunner.flow.orchestrator.load_and_build")
    def test_find_entry_explicit(self, mock_load):
        from initrunner.agent.schema.role import RoleDefinition

        role = RoleDefinition.model_validate(_make_role_data())
        mock_load.return_value = (role, MagicMock())

        flow = FlowDefinition.model_validate(_make_flow_data())
        orch = FlowOrchestrator(flow, Path("."))
        orch._build_members()

        entry = orch._find_entry("consumer")
        assert entry.name == "consumer"

    def test_service_health(self):
        flow = FlowDefinition.model_validate(_make_flow_data())
        orch = FlowOrchestrator(flow, Path("."))

        from initrunner.agent.schema.role import RoleDefinition

        role = RoleDefinition.model_validate(_make_role_data())
        for name in ["producer", "consumer"]:
            orch._members[name] = FlowMember(
                name=name,
                role=role,
                agent=MagicMock(),
                config=FlowAgentConfig(role=f"{name}.yaml"),
            )

        health = orch.agent_health()
        assert len(health) == 2
        assert all(h["runs"] == 0 for h in health)

    @patch("initrunner.flow.orchestrator.load_and_build")
    def test_role_sinks_built_when_no_flow_sink(self, mock_load):
        """When an agent has no flow sink, its role sinks should be built (daemon)."""
        from initrunner.agent.schema.role import RoleDefinition

        role_data = _make_role_data()
        role_data["spec"]["sinks"] = [{"type": "file", "path": "/tmp/out.txt"}]
        role = RoleDefinition.model_validate(role_data)
        mock_load.return_value = (role, MagicMock())

        flow_data = _make_flow_data({"standalone": {"role": "roles/standalone.yaml"}})
        flow = FlowDefinition.model_validate(flow_data)

        orch = FlowOrchestrator(flow, Path("."))
        with patch("initrunner.flow.orchestrator.build_sink") as mock_build_sink:
            mock_build_sink.return_value = MagicMock()
            orch._build_members(one_shot=False)

        assert mock_build_sink.call_count == 1

    @patch("initrunner.flow.orchestrator.load_and_build")
    def test_role_sinks_dropped_in_one_shot_mode(self, mock_load):
        """Role sinks are suppressed in one_shot mode."""
        from initrunner.agent.schema.role import RoleDefinition

        role_data = _make_role_data()
        role_data["spec"]["sinks"] = [{"type": "file", "path": "/tmp/out.txt"}]
        role = RoleDefinition.model_validate(role_data)
        mock_load.return_value = (role, MagicMock())

        flow = FlowDefinition.model_validate(_make_flow_data())
        orch = FlowOrchestrator(flow, Path("."))

        with patch("initrunner.flow.orchestrator.build_sink") as mock_build_sink:
            orch._build_members(one_shot=True)

        mock_build_sink.assert_not_called()


class TestSharedMemory:
    def test_shared_memory_patches_store_path(self):
        from initrunner.agent.schema.role import RoleDefinition

        role = RoleDefinition.model_validate(_make_role_data())
        apply_shared_memory(role, "/tmp/shared.db")

        assert role.spec.memory is not None
        assert role.spec.memory.store_path == "/tmp/shared.db"

    def test_shared_memory_max_memories_propagated(self):
        from initrunner.agent.schema.role import RoleDefinition

        role = RoleDefinition.model_validate(_make_role_data())
        apply_shared_memory(role, "/tmp/shared.db", max_memories=500)

        assert role.spec.memory.semantic.max_memories == 500  # type: ignore[unresolved-attribute]

    def test_shared_memory_overrides_existing_role_memory(self):
        from initrunner.agent.schema.memory import MemoryConfig, SemanticMemoryConfig
        from initrunner.agent.schema.role import RoleDefinition

        role_data = _make_role_data()
        role = RoleDefinition.model_validate(role_data)
        role.spec.memory = MemoryConfig(
            store_path="/original.db",
            semantic=SemanticMemoryConfig(max_memories=100),
        )

        apply_shared_memory(role, "/tmp/shared.db", max_memories=999)
        assert role.spec.memory.store_path == "/tmp/shared.db"
        assert role.spec.memory.semantic.max_memories == 999

    @patch("initrunner.flow.orchestrator.load_and_build")
    def test_no_shared_memory_uses_load_and_build(self, mock_load):
        from initrunner.agent.schema.role import RoleDefinition

        role = RoleDefinition.model_validate(_make_role_data())
        mock_load.return_value = (role, MagicMock())

        flow = FlowDefinition.model_validate(_make_flow_data())
        orch = FlowOrchestrator(flow, Path("."))
        orch._build_members()

        assert mock_load.call_count == 2
