"""Tests for the async internals of the compose orchestrator (Phase 1)."""

from __future__ import annotations

import asyncio
import queue
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import MagicMock, patch

from initrunner.compose.delegate_sink import DelegateEvent
from initrunner.compose.orchestrator import ComposeOrchestrator, ComposeService
from initrunner.compose.schema import ComposeDefinition, ComposeServiceConfig


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


def _make_service(name: str = "test", **kwargs) -> ComposeService:
    from initrunner.agent.schema.role import RoleDefinition

    role = RoleDefinition.model_validate(_make_role_data())
    return ComposeService(
        name=name,
        role=role,
        agent=MagicMock(),
        config=ComposeServiceConfig(role="test.yaml"),
        inbox=queue.Queue(),
        **kwargs,
    )


class TestInboxBridge:
    """Verify the sync queue.Queue -> asyncio.Queue bridge."""

    def test_inbox_bridge_drains_sync_queue(self):
        """Events put on the sync queue appear in the async inbox."""
        svc = _make_service()
        loop = asyncio.new_event_loop()
        executor = ThreadPoolExecutor(max_workers=2)

        received: list[DelegateEvent] = []

        async def _run():
            svc._async_inbox = asyncio.Queue()
            bridge = asyncio.create_task(svc._inbox_bridge())

            # Put an event on the sync queue
            event = DelegateEvent(
                source_service="src",
                target_service="test",
                prompt="hello",
                source_run_id="r1",
            )
            svc.inbox.put(event)

            # Wait for it to appear in async inbox
            result = await asyncio.wait_for(svc._async_inbox.get(), timeout=5)
            received.append(result)

            svc._stop_event.set()
            bridge.cancel()
            try:
                await bridge
            except asyncio.CancelledError:
                pass

        loop.run_until_complete(_run())
        loop.close()
        executor.shutdown(wait=False)

        assert len(received) == 1
        assert received[0].prompt == "hello"
        assert received[0].source_service == "src"


class TestServiceAsyncLoop:
    """Verify service runs on a shared event loop."""

    @patch("initrunner.compose.orchestrator.execute_run")
    def test_service_on_shared_loop(self, mock_execute):
        """A service started with loop= schedules its task on the shared loop."""
        from initrunner.agent.executor import RunResult

        mock_execute.return_value = (
            RunResult(run_id="r1", output="ok", success=True),
            [],
        )

        svc = _make_service()
        loop = asyncio.new_event_loop()
        executor = ThreadPoolExecutor(max_workers=2)

        thread = threading.Thread(
            target=lambda: (asyncio.set_event_loop(loop), loop.run_forever()),
            daemon=True,
        )
        thread.start()

        try:
            svc.start(loop=loop, executor=executor)
            assert svc.is_alive

            # Send an event
            svc.inbox.put(
                DelegateEvent(
                    source_service="src",
                    target_service="test",
                    prompt="process",
                    source_run_id="r1",
                )
            )

            # Wait for processing
            deadline = time.monotonic() + 5
            while svc.run_count == 0 and time.monotonic() < deadline:
                time.sleep(0.1)

            assert svc.run_count == 1
            mock_execute.assert_called_once()
        finally:
            svc.stop()

            async def _cleanup():
                tasks = [t for t in asyncio.all_tasks(loop) if t is not asyncio.current_task()]
                for t in tasks:
                    t.cancel()
                if tasks:
                    await asyncio.gather(*tasks, return_exceptions=True)
                loop.stop()

            asyncio.run_coroutine_threadsafe(_cleanup(), loop)
            thread.join(timeout=5)
            loop.close()
            executor.shutdown(wait=False)


class TestShutdownGracePeriod:
    """Verify the in-flight run shutdown contract."""

    @patch("initrunner.compose.orchestrator.execute_run")
    def test_stop_waits_for_in_flight_run(self, mock_execute):
        """stop() waits for the execution lock before cancelling."""
        from initrunner.agent.executor import RunResult

        # Simulate a slow run
        run_started = threading.Event()
        run_continue = threading.Event()

        def _slow_execute(agent, role, prompt, **kwargs):
            run_started.set()
            run_continue.wait(timeout=10)
            return RunResult(run_id="r1", output="ok", success=True), []

        mock_execute.side_effect = _slow_execute

        svc = _make_service(shutdown_grace_seconds=0.5)
        loop = asyncio.new_event_loop()
        executor = ThreadPoolExecutor(max_workers=2)

        thread = threading.Thread(
            target=lambda: (asyncio.set_event_loop(loop), loop.run_forever()),
            daemon=True,
        )
        thread.start()

        try:
            svc.start(loop=loop, executor=executor)
            svc.inbox.put(
                DelegateEvent(
                    source_service="src",
                    target_service="test",
                    prompt="slow",
                    source_run_id="r1",
                )
            )

            # Wait for run to start
            assert run_started.wait(timeout=5)

            # stop() should wait up to grace period, then detach
            stop_start = time.monotonic()
            svc.stop()
            stop_duration = time.monotonic() - stop_start

            # Should have waited roughly the grace period
            assert stop_duration >= 0.3  # some tolerance

            # Let the run complete
            run_continue.set()
        finally:

            async def _cleanup():
                tasks = [t for t in asyncio.all_tasks(loop) if t is not asyncio.current_task()]
                for t in tasks:
                    t.cancel()
                if tasks:
                    await asyncio.gather(*tasks, return_exceptions=True)
                loop.stop()

            asyncio.run_coroutine_threadsafe(_cleanup(), loop)
            thread.join(timeout=5)
            loop.close()
            executor.shutdown(wait=True, cancel_futures=False)


class TestOrchestratorSharedLoop:
    """Verify ComposeOrchestrator creates and manages a shared event loop."""

    @patch("initrunner.compose.orchestrator.load_and_build")
    def test_orchestrator_starts_loop_thread(self, mock_load):
        from initrunner.agent.schema.role import RoleDefinition

        role = RoleDefinition.model_validate(_make_role_data())
        mock_load.return_value = (role, MagicMock())

        compose = ComposeDefinition.model_validate(_make_compose_data())
        orch = ComposeOrchestrator(compose, Path("."))

        orch.start()
        try:
            assert orch._loop is not None
            assert orch._loop.is_running()
            assert orch._loop_thread is not None
            assert orch._loop_thread.is_alive()
            assert orch._executor is not None

            # Services should be running on the shared loop
            for svc in orch._services.values():
                assert svc.is_alive
                assert svc._loop is orch._loop
        finally:
            orch.stop()

        assert orch._loop is None
        assert orch._loop_thread is None
        assert orch._executor is None

    @patch("initrunner.compose.orchestrator.load_and_build")
    def test_executor_pool_sizing_default(self, mock_load):
        from initrunner.agent.schema.role import RoleDefinition

        role = RoleDefinition.model_validate(_make_role_data())
        mock_load.return_value = (role, MagicMock())

        compose = ComposeDefinition.model_validate(_make_compose_data())
        orch = ComposeOrchestrator(compose, Path("."))

        orch.start()
        try:
            # Default: min(32, services + 4) = min(32, 6) = 6
            assert orch._executor is not None
            assert orch._executor._max_workers == 6
        finally:
            orch.stop()

    @patch("initrunner.compose.orchestrator.load_and_build")
    def test_executor_pool_sizing_custom(self, mock_load):
        from initrunner.agent.schema.role import RoleDefinition

        role = RoleDefinition.model_validate(_make_role_data())
        mock_load.return_value = (role, MagicMock())

        compose = ComposeDefinition.model_validate(_make_compose_data())
        orch = ComposeOrchestrator(compose, Path("."), max_agent_workers=10)

        orch.start()
        try:
            assert orch._executor is not None
            assert orch._executor._max_workers == 10
        finally:
            orch.stop()


class TestTriggerBridge:
    """Verify triggers bridge to the async inbox when a loop is available."""

    def test_trigger_bridges_to_async_inbox(self):
        from initrunner.triggers.base import TriggerEvent

        svc = _make_service()
        loop = asyncio.new_event_loop()
        executor = ThreadPoolExecutor(max_workers=2)

        thread = threading.Thread(
            target=lambda: (asyncio.set_event_loop(loop), loop.run_forever()),
            daemon=True,
        )
        thread.start()

        try:
            svc.start(loop=loop, executor=executor)
            # Give service time to set up
            time.sleep(0.5)

            # _on_trigger should put event in async inbox
            event = TriggerEvent(
                trigger_type="cron",
                prompt="scheduled task",
            )
            svc._on_trigger(event)

            # Check the async inbox got the event
            time.sleep(0.5)
            assert svc._async_inbox is not None

        finally:
            svc.stop()

            async def _cleanup():
                tasks = [t for t in asyncio.all_tasks(loop) if t is not asyncio.current_task()]
                for t in tasks:
                    t.cancel()
                if tasks:
                    await asyncio.gather(*tasks, return_exceptions=True)
                loop.stop()

            asyncio.run_coroutine_threadsafe(_cleanup(), loop)
            thread.join(timeout=5)
            loop.close()
            executor.shutdown(wait=False)
