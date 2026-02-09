"""Tests for the compose orchestrator."""

from __future__ import annotations

import queue
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

from initrunner.compose.delegate_sink import DelegateEvent, DelegateSink
from initrunner.compose.orchestrator import (
    ComposeOrchestrator,
    ComposeService,
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
            "model": {"provider": "openai", "name": "gpt-4o-mini"},
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
        from initrunner.agent.schema import RoleDefinition

        role = RoleDefinition.model_validate(_make_role_data())
        agent = MagicMock()
        inbox: queue.Queue[DelegateEvent] = queue.Queue()

        svc = ComposeService(
            name="test",
            role=role,
            agent=agent,
            config=ComposeServiceConfig(role="test.yaml"),
            inbox=inbox,
        )

        assert svc.name == "test"
        assert svc.run_count == 0
        assert svc.error_count == 0
        assert not svc.is_alive

    def test_add_sink(self):
        from initrunner.agent.schema import RoleDefinition

        role = RoleDefinition.model_validate(_make_role_data())
        agent = MagicMock()
        inbox: queue.Queue[DelegateEvent] = queue.Queue()

        svc = ComposeService(
            name="test",
            role=role,
            agent=agent,
            config=ComposeServiceConfig(role="test.yaml"),
            inbox=inbox,
        )

        mock_sink = MagicMock()
        svc.add_sink(mock_sink)
        assert svc._sink_dispatcher.count == 1

    def test_start_stop(self):
        from initrunner.agent.schema import RoleDefinition

        role = RoleDefinition.model_validate(_make_role_data())
        agent = MagicMock()
        inbox: queue.Queue[DelegateEvent] = queue.Queue()

        svc = ComposeService(
            name="test",
            role=role,
            agent=agent,
            config=ComposeServiceConfig(role="test.yaml"),
            inbox=inbox,
        )

        svc.start()
        assert svc.is_alive

        svc.stop()
        time.sleep(0.1)
        assert not svc.is_alive

    @patch("initrunner.compose.orchestrator.execute_run")
    def test_handles_delegate_event(self, mock_execute):
        from initrunner.agent.executor import RunResult
        from initrunner.agent.schema import RoleDefinition

        mock_execute.return_value = (
            RunResult(run_id="r1", output="response", success=True),
            [],
        )

        role = RoleDefinition.model_validate(_make_role_data())
        agent = MagicMock()
        inbox: queue.Queue[DelegateEvent] = queue.Queue()

        svc = ComposeService(
            name="consumer",
            role=role,
            agent=agent,
            config=ComposeServiceConfig(role="test.yaml"),
            inbox=inbox,
        )

        svc.start()

        # Enqueue a delegate event
        inbox.put(
            DelegateEvent(
                source_service="producer",
                target_service="consumer",
                prompt="process this",
                source_run_id="p1",
            )
        )

        # Wait for processing
        time.sleep(1)
        svc.stop()

        mock_execute.assert_called_once()
        assert svc.run_count == 1

    @patch("initrunner.compose.orchestrator.execute_run")
    def test_dispatches_to_sinks(self, mock_execute):
        from initrunner.agent.executor import RunResult
        from initrunner.agent.schema import RoleDefinition

        mock_execute.return_value = (
            RunResult(run_id="r1", output="response", success=True),
            [],
        )

        role = RoleDefinition.model_validate(_make_role_data())
        agent = MagicMock()
        inbox: queue.Queue[DelegateEvent] = queue.Queue()

        svc = ComposeService(
            name="test",
            role=role,
            agent=agent,
            config=ComposeServiceConfig(role="test.yaml"),
            inbox=inbox,
        )

        mock_sink = MagicMock()
        svc.add_sink(mock_sink)

        svc.start()
        inbox.put(
            DelegateEvent(
                source_service="other",
                target_service="test",
                prompt="go",
                source_run_id="x1",
            )
        )

        time.sleep(1)
        svc.stop()

        mock_sink.send.assert_called_once()

    @patch("initrunner.compose.orchestrator.execute_run")
    def test_error_count_incremented(self, mock_execute):
        from initrunner.agent.executor import RunResult
        from initrunner.agent.schema import RoleDefinition

        mock_execute.return_value = (
            RunResult(run_id="r1", success=False, error="fail"),
            [],
        )

        role = RoleDefinition.model_validate(_make_role_data())
        agent = MagicMock()
        inbox: queue.Queue[DelegateEvent] = queue.Queue()

        svc = ComposeService(
            name="test",
            role=role,
            agent=agent,
            config=ComposeServiceConfig(role="test.yaml"),
            inbox=inbox,
        )

        svc.start()
        inbox.put(
            DelegateEvent(
                source_service="other",
                target_service="test",
                prompt="go",
                source_run_id="x1",
            )
        )

        time.sleep(1)
        svc.stop()

        assert svc.error_count == 1


class TestComposeOrchestrator:
    def test_topological_order_no_deps(self):
        compose = ComposeDefinition.model_validate(
            _make_compose_data(
                {
                    "a": {"role": "a.yaml"},
                    "b": {"role": "b.yaml"},
                    "c": {"role": "c.yaml"},
                }
            )
        )
        orch = ComposeOrchestrator(compose, Path("."))
        # Build services manually to test topological_order
        orch._compose = compose
        # Without building services, topological order uses compose spec
        # Create minimal services dict
        for name in compose.spec.services:
            orch._services[name] = MagicMock()

        tiers = orch._topological_order()
        # All in one tier since no deps
        assert len(tiers) == 1
        assert sorted(tiers[0]) == ["a", "b", "c"]

    def test_topological_order_with_deps(self):
        compose = ComposeDefinition.model_validate(
            _make_compose_data(
                {
                    "a": {"role": "a.yaml"},
                    "b": {"role": "b.yaml", "depends_on": ["a"]},
                    "c": {"role": "c.yaml", "depends_on": ["b"]},
                }
            )
        )
        orch = ComposeOrchestrator(compose, Path("."))
        for name in compose.spec.services:
            orch._services[name] = MagicMock()

        tiers = orch._topological_order()
        assert len(tiers) == 3
        assert tiers[0] == ["a"]
        assert tiers[1] == ["b"]
        assert tiers[2] == ["c"]

    @patch("initrunner.compose.orchestrator.load_and_build")
    def test_build_services(self, mock_load):
        from initrunner.agent.schema import RoleDefinition

        role = RoleDefinition.model_validate(_make_role_data())
        mock_load.return_value = (role, MagicMock())

        compose = ComposeDefinition.model_validate(_make_compose_data())
        orch = ComposeOrchestrator(compose, Path("."))
        orch._build_services()

        assert "producer" in orch._services
        assert "consumer" in orch._services
        assert mock_load.call_count == 2

    @patch("initrunner.compose.orchestrator.load_and_build")
    def test_wire_delegates(self, mock_load):
        from initrunner.agent.schema import RoleDefinition

        role = RoleDefinition.model_validate(_make_role_data())
        mock_load.return_value = (role, MagicMock())

        compose = ComposeDefinition.model_validate(_make_compose_data())
        orch = ComposeOrchestrator(compose, Path("."))
        orch._build_services()
        orch._wire_delegates()

        # Producer should have a DelegateSink pointing to consumer's inbox
        producer = orch._services["producer"]
        assert producer._sink_dispatcher.count == 1
        assert isinstance(producer._sink_dispatcher._sinks[0], DelegateSink)

    @patch("initrunner.compose.orchestrator.load_and_build")
    def test_context_manager(self, mock_load):
        from initrunner.agent.schema import RoleDefinition

        role = RoleDefinition.model_validate(_make_role_data())
        mock_load.return_value = (role, MagicMock())

        compose = ComposeDefinition.model_validate(_make_compose_data())

        with ComposeOrchestrator(compose, Path(".")) as orch:
            assert "producer" in orch.services
            assert "consumer" in orch.services
            # Services should be running
            for svc in orch._services.values():
                assert svc.is_alive

        # After exit, services should be stopped
        for svc in orch._services.values():
            assert not svc.is_alive

    @patch("initrunner.compose.orchestrator.execute_run")
    @patch("initrunner.compose.orchestrator.load_and_build")
    def test_end_to_end_delegation(self, mock_load, mock_execute):
        """Producer output flows to consumer inbox via DelegateSink."""
        from initrunner.agent.executor import RunResult
        from initrunner.agent.schema import RoleDefinition

        role = RoleDefinition.model_validate(_make_role_data())
        mock_agent = MagicMock()
        mock_load.return_value = (role, mock_agent)

        call_count = 0

        def _execute_side_effect(agent, role, prompt, **kwargs):
            nonlocal call_count
            call_count += 1
            return RunResult(run_id=f"r{call_count}", output=f"output-{call_count}"), []

        mock_execute.side_effect = _execute_side_effect

        compose = ComposeDefinition.model_validate(_make_compose_data())

        with ComposeOrchestrator(compose, Path(".")) as orch:
            # Inject a trigger-like event into producer's inbox
            producer = orch._services["producer"]
            producer.inbox.put(
                DelegateEvent(
                    source_service="external",
                    target_service="producer",
                    prompt="initial input",
                    source_run_id="ext1",
                )
            )

            # Wait for both producer and consumer to process
            time.sleep(2)

        # Producer handled initial event, consumer handled delegate
        assert call_count >= 2

    @patch("initrunner.compose.orchestrator.build_sink")
    @patch("initrunner.compose.orchestrator.load_and_build")
    def test_role_sinks_built_when_no_compose_sink(self, mock_load, mock_build_sink):
        """Role with sinks and no compose sink: role sinks are active."""
        from initrunner.agent.schema import RoleDefinition

        role_data = _make_role_data()
        role_data["spec"]["sinks"] = [{"type": "file", "path": "out.json"}]
        role = RoleDefinition.model_validate(role_data)
        mock_load.return_value = (role, MagicMock())

        mock_sink_instance = MagicMock()
        mock_build_sink.return_value = mock_sink_instance

        compose = ComposeDefinition.model_validate(
            _make_compose_data(
                {"svc": {"role": "roles/svc.yaml"}}  # no sink
            )
        )
        orch = ComposeOrchestrator(compose, Path("."))
        orch._build_services()

        svc = orch._services["svc"]
        assert mock_sink_instance in svc._sink_dispatcher._sinks

    @patch("initrunner.compose.orchestrator.load_and_build")
    def test_role_sinks_dropped_when_delegate_without_keep(self, mock_load):
        """Role with sinks + delegate sink (keep=false): role sinks not built."""
        from initrunner.agent.schema import RoleDefinition

        role_data = _make_role_data()
        role_data["spec"]["sinks"] = [{"type": "file", "path": "out.json"}]
        role = RoleDefinition.model_validate(role_data)
        mock_load.return_value = (role, MagicMock())

        compose = ComposeDefinition.model_validate(
            _make_compose_data(
                {
                    "producer": {
                        "role": "roles/producer.yaml",
                        "sink": {"type": "delegate", "target": "consumer"},
                    },
                    "consumer": {"role": "roles/consumer.yaml"},
                }
            )
        )
        orch = ComposeOrchestrator(compose, Path("."))
        orch._build_services()

        # Role sinks should NOT be built for producer (keep_existing_sinks defaults false)
        producer = orch._services["producer"]
        assert producer._sink_dispatcher.count == 0

    @patch("initrunner.compose.orchestrator.build_sink")
    @patch("initrunner.compose.orchestrator.load_and_build")
    def test_role_sinks_kept_with_keep_existing(self, mock_load, mock_build_sink):
        """Role with sinks + delegate sink (keep=true): role sinks built alongside delegate."""
        from initrunner.agent.schema import RoleDefinition

        role_data = _make_role_data()
        role_data["spec"]["sinks"] = [{"type": "file", "path": "out.json"}]
        role = RoleDefinition.model_validate(role_data)
        mock_load.return_value = (role, MagicMock())

        mock_sink_instance = MagicMock()
        mock_build_sink.return_value = mock_sink_instance

        compose = ComposeDefinition.model_validate(
            _make_compose_data(
                {
                    "producer": {
                        "role": "roles/producer.yaml",
                        "sink": {
                            "type": "delegate",
                            "target": "consumer",
                            "keep_existing_sinks": True,
                        },
                    },
                    "consumer": {"role": "roles/consumer.yaml"},
                }
            )
        )
        orch = ComposeOrchestrator(compose, Path("."))
        orch._build_services()

        producer = orch._services["producer"]
        assert mock_sink_instance in producer._sink_dispatcher._sinks

    @patch("initrunner.compose.orchestrator.execute_run")
    def test_session_pruning_called(self, mock_execute):
        """Memory session pruning is called after each execution."""
        from initrunner.agent.executor import RunResult
        from initrunner.agent.schema import RoleDefinition

        role_data = _make_role_data()
        role_data["spec"]["memory"] = {}  # enable memory with defaults
        role = RoleDefinition.model_validate(role_data)

        mock_execute.return_value = (
            RunResult(run_id="r1", output="ok", success=True),
            [],
        )

        agent = MagicMock()
        inbox: queue.Queue[DelegateEvent] = queue.Queue()

        svc = ComposeService(
            name="test",
            role=role,
            agent=agent,
            config=ComposeServiceConfig(role="test.yaml"),
            inbox=inbox,
        )

        mock_store = MagicMock()
        with (
            patch("initrunner.stores.factory.create_memory_store") as mock_create,
            patch("initrunner.stores.base.resolve_memory_path"),
        ):
            mock_create.return_value.__enter__ = MagicMock(return_value=mock_store)
            mock_create.return_value.__exit__ = MagicMock(return_value=False)

            svc.start()
            inbox.put(
                DelegateEvent(
                    source_service="other",
                    target_service="test",
                    prompt="go",
                    source_run_id="x1",
                )
            )

            time.sleep(1)
            svc.stop()

        assert role.spec.memory is not None
        mock_store.prune_sessions.assert_called_once_with(
            "test-agent", role.spec.memory.max_sessions
        )


class TestDelegateHealth:
    @patch("initrunner.compose.orchestrator.load_and_build")
    def test_delegate_health_returns_per_sink_info(self, mock_load):
        from initrunner.agent.schema import RoleDefinition

        role = RoleDefinition.model_validate(_make_role_data())
        mock_load.return_value = (role, MagicMock())

        compose = ComposeDefinition.model_validate(_make_compose_data())
        orch = ComposeOrchestrator(compose, Path("."))
        orch._build_services()
        orch._wire_delegates()

        health = orch.delegate_health()
        assert len(health) == 1
        assert health[0]["source"] == "producer"
        assert health[0]["target"] == "consumer"
        assert health[0]["dropped_count"] == 0
        assert health[0]["filtered_count"] == 0

    @patch("initrunner.compose.orchestrator.load_and_build")
    def test_audit_logger_passed_to_sinks(self, mock_load, tmp_path):
        from initrunner.agent.schema import RoleDefinition
        from initrunner.audit.logger import AuditLogger

        role = RoleDefinition.model_validate(_make_role_data())
        mock_load.return_value = (role, MagicMock())

        compose = ComposeDefinition.model_validate(_make_compose_data())
        db_path = tmp_path / "audit.db"
        with AuditLogger(db_path) as audit_logger:
            orch = ComposeOrchestrator(compose, Path("."), audit_logger=audit_logger)
            orch._build_services()
            orch._wire_delegates()

            # Check that delegate sinks have audit_logger
            assert len(orch._delegate_sinks) == 1
            assert orch._delegate_sinks[0]._audit_logger is audit_logger

    @patch("initrunner.compose.orchestrator.load_and_build")
    def test_stop_flushes_delegate_sinks(self, mock_load, tmp_path):
        from initrunner.agent.schema import RoleDefinition
        from initrunner.audit.logger import AuditLogger

        role = RoleDefinition.model_validate(_make_role_data())
        mock_load.return_value = (role, MagicMock())

        compose = ComposeDefinition.model_validate(_make_compose_data())
        db_path = tmp_path / "audit.db"
        with AuditLogger(db_path) as audit_logger:
            orch = ComposeOrchestrator(compose, Path("."), audit_logger=audit_logger)
            orch.start()

            # Verify sinks are tracked
            assert len(orch._delegate_sinks) == 1

            orch.stop()

            # After stop, flush thread should be stopped
            for sink in orch._delegate_sinks:
                assert sink._flush_stop.is_set()


class TestComposeServiceThreadSafety:
    @patch("initrunner.compose.orchestrator.execute_run")
    def test_concurrent_handle_prompt_counter_accuracy(self, mock_execute):
        """N threads calling _handle_prompt — run_count and error_count must be exact."""
        from initrunner.agent.executor import RunResult
        from initrunner.agent.schema import RoleDefinition

        n_threads = 16
        calls_per_thread = 20
        # Even-numbered calls succeed, odd fail
        call_index = {"value": 0}
        call_lock = threading.Lock()

        def _execute_side_effect(agent, role, prompt, **kwargs):
            with call_lock:
                idx = call_index["value"]
                call_index["value"] += 1
            success = idx % 2 == 0
            return (
                RunResult(
                    run_id=f"r{idx}",
                    output="ok" if success else "fail",
                    success=success,
                    error=None if success else "err",
                ),
                [],
            )

        mock_execute.side_effect = _execute_side_effect

        role = RoleDefinition.model_validate(_make_role_data())
        agent = MagicMock()
        inbox: queue.Queue[DelegateEvent] = queue.Queue()

        svc = ComposeService(
            name="test",
            role=role,
            agent=agent,
            config=ComposeServiceConfig(role="test.yaml"),
            inbox=inbox,
        )

        barrier = threading.Barrier(n_threads)

        def _worker() -> None:
            barrier.wait()
            for _ in range(calls_per_thread):
                svc._handle_prompt("test prompt")

        threads = [threading.Thread(target=_worker) for _ in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        total = n_threads * calls_per_thread
        assert svc.run_count == total
        assert svc.error_count == total // 2


class TestSharedMemory:
    """Tests for compose shared_memory wiring."""

    def _compose_with_shared_memory(
        self, *, store_path: str | None = None, max_memories: int = 1000
    ) -> dict:
        return {
            "apiVersion": "initrunner/v1",
            "kind": "Compose",
            "metadata": {"name": "mem-compose"},
            "spec": {
                "services": {
                    "researcher": {"role": "roles/researcher.yaml"},
                    "writer": {"role": "roles/writer.yaml"},
                },
                "shared_memory": {
                    "enabled": True,
                    "store_path": store_path,
                    "max_memories": max_memories,
                },
            },
        }

    @patch("initrunner.compose.orchestrator.build_agent")
    @patch("initrunner.compose.orchestrator.load_role")
    @patch("initrunner.compose.orchestrator._load_dotenv")
    def test_shared_memory_patches_store_path(self, mock_dotenv, mock_load, mock_build):
        from initrunner.agent.schema import RoleDefinition

        roles = {}

        def _load_side_effect(path):
            role = RoleDefinition.model_validate(_make_role_data())
            roles[str(path)] = role
            return role

        mock_load.side_effect = _load_side_effect
        mock_build.return_value = MagicMock()

        compose = ComposeDefinition.model_validate(
            self._compose_with_shared_memory(store_path="/tmp/shared.db")
        )
        orch = ComposeOrchestrator(compose, Path("."))
        orch._build_services()

        # All roles should have memory pointing to the shared path
        for role in roles.values():
            assert role.spec.memory is not None
            assert role.spec.memory.store_path == "/tmp/shared.db"

    @patch("initrunner.compose.orchestrator.build_agent")
    @patch("initrunner.compose.orchestrator.load_role")
    @patch("initrunner.compose.orchestrator._load_dotenv")
    def test_shared_memory_default_path(self, mock_dotenv, mock_load, mock_build):
        from initrunner.agent.schema import RoleDefinition

        roles = {}

        def _load_side_effect(path):
            role = RoleDefinition.model_validate(_make_role_data())
            roles[str(path)] = role
            return role

        mock_load.side_effect = _load_side_effect
        mock_build.return_value = MagicMock()

        compose = ComposeDefinition.model_validate(
            self._compose_with_shared_memory()  # no store_path
        )
        orch = ComposeOrchestrator(compose, Path("."))
        orch._build_services()

        for role in roles.values():
            assert role.spec.memory is not None
            assert role.spec.memory.store_path is not None
            assert "mem-compose-shared.db" in role.spec.memory.store_path

    @patch("initrunner.compose.orchestrator.build_agent")
    @patch("initrunner.compose.orchestrator.load_role")
    @patch("initrunner.compose.orchestrator._load_dotenv")
    def test_shared_memory_max_memories_propagated(self, mock_dotenv, mock_load, mock_build):
        from initrunner.agent.schema import RoleDefinition

        roles = {}

        def _load_side_effect(path):
            role = RoleDefinition.model_validate(_make_role_data())
            roles[str(path)] = role
            return role

        mock_load.side_effect = _load_side_effect
        mock_build.return_value = MagicMock()

        compose = ComposeDefinition.model_validate(
            self._compose_with_shared_memory(store_path="/tmp/shared.db", max_memories=500)
        )
        orch = ComposeOrchestrator(compose, Path("."))
        orch._build_services()

        for role in roles.values():
            assert role.spec.memory is not None
            assert role.spec.memory.max_memories == 500

    @patch("initrunner.compose.orchestrator.build_agent")
    @patch("initrunner.compose.orchestrator.load_role")
    @patch("initrunner.compose.orchestrator._load_dotenv")
    def test_shared_memory_overrides_existing_role_memory(self, mock_dotenv, mock_load, mock_build):
        from initrunner.agent.schema import RoleDefinition

        roles = {}

        def _load_side_effect(path):
            role_data = _make_role_data()
            role_data["spec"]["memory"] = {
                "store_path": "/original/path.db",
                "max_memories": 2000,
            }
            role = RoleDefinition.model_validate(role_data)
            roles[str(path)] = role
            return role

        mock_load.side_effect = _load_side_effect
        mock_build.return_value = MagicMock()

        compose = ComposeDefinition.model_validate(
            self._compose_with_shared_memory(store_path="/tmp/shared.db", max_memories=500)
        )
        orch = ComposeOrchestrator(compose, Path("."))
        orch._build_services()

        for role in roles.values():
            assert role.spec.memory is not None
            assert role.spec.memory.store_path == "/tmp/shared.db"
            assert role.spec.memory.max_memories == 500

    @patch("initrunner.compose.orchestrator.load_and_build")
    def test_no_shared_memory_uses_load_and_build(self, mock_load):
        """Without shared memory, the standard load_and_build path is used."""
        from initrunner.agent.schema import RoleDefinition

        role = RoleDefinition.model_validate(_make_role_data())
        mock_load.return_value = (role, MagicMock())

        compose = ComposeDefinition.model_validate(
            _make_compose_data({"svc": {"role": "roles/svc.yaml"}})
        )
        orch = ComposeOrchestrator(compose, Path("."))
        orch._build_services()

        mock_load.assert_called_once()
        assert role.spec.memory is None  # untouched
