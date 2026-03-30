"""Tests for the compose orchestrator (graph-based)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from initrunner.compose.orchestrator import (
    ComposeOrchestrator,
    ComposeService,
    apply_shared_memory,
)
from initrunner.compose.schema import (
    ComposeDefinition,
    ComposeServiceConfig,
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


def _make_compose_data(services: dict | None = None) -> dict:
    if services is None:
        services = {
            "producer": {
                "role": "roles/producer.yaml",
                "sink": {"type": "delegate", "target": "consumer"},
            },
            "consumer": {"role": "roles/consumer.yaml"},
        }
    return {
        "apiVersion": "initrunner/v1",
        "kind": "Compose",
        "metadata": {"name": "test-compose"},
        "spec": {"services": services},
    }


class TestComposeService:
    def test_creation(self):
        from initrunner.agent.schema.role import RoleDefinition

        role = RoleDefinition.model_validate(_make_role_data())
        agent = MagicMock()

        svc = ComposeService(
            name="test",
            role=role,
            agent=agent,
            config=ComposeServiceConfig(role="test.yaml"),
        )

        assert svc.name == "test"
        assert svc.run_count == 0
        assert svc.error_count == 0
        assert svc.is_alive

    def test_add_sink(self):
        from initrunner.agent.schema.role import RoleDefinition

        role = RoleDefinition.model_validate(_make_role_data())
        agent = MagicMock()

        svc = ComposeService(
            name="test",
            role=role,
            agent=agent,
            config=ComposeServiceConfig(role="test.yaml"),
        )

        mock_sink = MagicMock()
        svc.add_sink(mock_sink)
        assert svc._sink_dispatcher.count == 1


class TestComposeOrchestrator:
    def test_topological_order_no_deps(self):
        compose = ComposeDefinition.model_validate(
            _make_compose_data(
                {
                    "svc-a": {"role": "a.yaml"},
                    "svc-b": {"role": "b.yaml"},
                    "svc-c": {"role": "c.yaml"},
                }
            )
        )
        orch = ComposeOrchestrator(compose, Path("."))
        for name in compose.spec.services:
            orch._services[name] = MagicMock()

        tiers = orch._topological_order()
        assert len(tiers) == 1
        assert sorted(tiers[0]) == ["svc-a", "svc-b", "svc-c"]

    def test_topological_order_with_deps(self):
        compose = ComposeDefinition.model_validate(
            _make_compose_data(
                {
                    "svc-a": {"role": "a.yaml"},
                    "svc-b": {"role": "b.yaml", "depends_on": ["svc-a"]},
                    "svc-c": {"role": "c.yaml", "depends_on": ["svc-b"]},
                }
            )
        )
        orch = ComposeOrchestrator(compose, Path("."))
        for name in compose.spec.services:
            orch._services[name] = MagicMock()

        tiers = orch._topological_order()
        assert len(tiers) == 3
        assert tiers[0] == ["svc-a"]
        assert tiers[1] == ["svc-b"]
        assert tiers[2] == ["svc-c"]

    @patch("initrunner.compose.orchestrator.load_and_build")
    def test_build_services(self, mock_load):
        from initrunner.agent.schema.role import RoleDefinition

        role = RoleDefinition.model_validate(_make_role_data())
        mock_load.return_value = (role, MagicMock())

        compose = ComposeDefinition.model_validate(_make_compose_data())
        orch = ComposeOrchestrator(compose, Path("."))
        orch._build_services()

        assert "producer" in orch._services
        assert "consumer" in orch._services
        assert mock_load.call_count == 2

    @patch("initrunner.compose.orchestrator.load_and_build")
    def test_find_entry(self, mock_load):
        from initrunner.agent.schema.role import RoleDefinition

        role = RoleDefinition.model_validate(_make_role_data())
        mock_load.return_value = (role, MagicMock())

        compose = ComposeDefinition.model_validate(_make_compose_data())
        orch = ComposeOrchestrator(compose, Path("."))
        orch._build_services()

        entry = orch._find_entry()
        assert entry.name == "producer"

    @patch("initrunner.compose.orchestrator.load_and_build")
    def test_find_entry_explicit(self, mock_load):
        from initrunner.agent.schema.role import RoleDefinition

        role = RoleDefinition.model_validate(_make_role_data())
        mock_load.return_value = (role, MagicMock())

        compose = ComposeDefinition.model_validate(_make_compose_data())
        orch = ComposeOrchestrator(compose, Path("."))
        orch._build_services()

        entry = orch._find_entry("consumer")
        assert entry.name == "consumer"

    def test_service_health(self):
        compose = ComposeDefinition.model_validate(_make_compose_data())
        orch = ComposeOrchestrator(compose, Path("."))

        from initrunner.agent.schema.role import RoleDefinition

        role = RoleDefinition.model_validate(_make_role_data())
        for name in ["producer", "consumer"]:
            orch._services[name] = ComposeService(
                name=name,
                role=role,
                agent=MagicMock(),
                config=ComposeServiceConfig(role=f"{name}.yaml"),
            )

        health = orch.service_health()
        assert len(health) == 2
        assert all(h["runs"] == 0 for h in health)

    @patch("initrunner.compose.orchestrator.load_and_build")
    def test_role_sinks_built_when_no_compose_sink(self, mock_load):
        """When a service has no compose sink, its role sinks should be built (daemon)."""
        from initrunner.agent.schema.role import RoleDefinition

        role_data = _make_role_data()
        role_data["spec"]["sinks"] = [{"type": "file", "path": "/tmp/out.txt"}]
        role = RoleDefinition.model_validate(role_data)
        mock_load.return_value = (role, MagicMock())

        compose_data = _make_compose_data(
            {"standalone": {"role": "roles/standalone.yaml"}}
        )
        compose = ComposeDefinition.model_validate(compose_data)

        orch = ComposeOrchestrator(compose, Path("."))
        with patch("initrunner.compose.orchestrator.build_sink") as mock_build_sink:
            mock_build_sink.return_value = MagicMock()
            orch._build_services(one_shot=False)

        assert mock_build_sink.call_count == 1

    @patch("initrunner.compose.orchestrator.load_and_build")
    def test_role_sinks_dropped_in_one_shot_mode(self, mock_load):
        """Role sinks are suppressed in one_shot mode."""
        from initrunner.agent.schema.role import RoleDefinition

        role_data = _make_role_data()
        role_data["spec"]["sinks"] = [{"type": "file", "path": "/tmp/out.txt"}]
        role = RoleDefinition.model_validate(role_data)
        mock_load.return_value = (role, MagicMock())

        compose = ComposeDefinition.model_validate(_make_compose_data())
        orch = ComposeOrchestrator(compose, Path("."))

        with patch("initrunner.compose.orchestrator.build_sink") as mock_build_sink:
            orch._build_services(one_shot=True)

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

        assert role.spec.memory.semantic.max_memories == 500

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

    @patch("initrunner.compose.orchestrator.load_and_build")
    def test_no_shared_memory_uses_load_and_build(self, mock_load):
        from initrunner.agent.schema.role import RoleDefinition

        role = RoleDefinition.model_validate(_make_role_data())
        mock_load.return_value = (role, MagicMock())

        compose = ComposeDefinition.model_validate(_make_compose_data())
        orch = ComposeOrchestrator(compose, Path("."))
        orch._build_services()

        assert mock_load.call_count == 2
