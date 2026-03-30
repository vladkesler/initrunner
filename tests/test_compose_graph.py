"""Tests for graph-based compose execution."""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import anyio
import pytest

from initrunner.agent.executor import RunResult
from initrunner.compose.graph import (
    ComposeGraphDeps,
    DelegationEnvelope,
    _ServiceRef,
    build_compose_graph,
    run_compose_graph_sync,
)
from initrunner.compose.schema import ComposeDefinition


def _make_role_data(name: str = "test-agent") -> dict:
    return {
        "apiVersion": "initrunner/v1",
        "kind": "Agent",
        "metadata": {"name": name, "description": f"{name} role"},
        "spec": {
            "role": f"You are {name}.",
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


def _make_service_ref(name: str) -> _ServiceRef:
    from initrunner.agent.schema.role import RoleDefinition

    role = RoleDefinition.model_validate(_make_role_data(name))
    agent = MagicMock()
    return _ServiceRef(
        name=name,
        role=role,
        agent=agent,
        sink_dispatcher=None,
    )


def _make_run_result(output: str = "done", success: bool = True) -> RunResult:
    r = RunResult(run_id="test-run")
    r.output = output
    r.success = success
    r.tokens_in = 10
    r.tokens_out = 20
    r.duration_ms = 100
    if not success:
        r.error = "failed"
    return r


class TestBuildComposeGraph:
    def test_linear_chain_builds(self):
        compose = ComposeDefinition.model_validate(_make_compose_data())
        refs = {
            "producer": _make_service_ref("producer"),
            "consumer": _make_service_ref("consumer"),
        }
        graph, entry = build_compose_graph(compose, refs)
        assert entry == "producer"
        assert graph is not None

    def test_fan_out_builds(self):
        data = _make_compose_data(
            {
                "entry": {
                    "role": "roles/entry.yaml",
                    "sink": {"type": "delegate", "target": ["svc-a", "svc-b"]},
                },
                "svc-a": {"role": "roles/a.yaml"},
                "svc-b": {"role": "roles/b.yaml"},
            }
        )
        compose = ComposeDefinition.model_validate(data)
        refs = {n: _make_service_ref(n) for n in ["entry", "svc-a", "svc-b"]}
        graph, entry = build_compose_graph(compose, refs)
        assert entry == "entry"

    def test_diamond_builds(self):
        data = _make_compose_data(
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
        compose = ComposeDefinition.model_validate(data)
        refs = {n: _make_service_ref(n) for n in ["entry", "svc-a", "svc-b", "final"]}
        graph, entry = build_compose_graph(compose, refs)
        assert entry == "entry"


class TestRunComposeGraph:
    @patch("initrunner.compose.graph.execute_run_async")
    def test_linear_chain_execution(self, mock_exec):
        """A->B: both run in order, B gets A's output."""
        call_order = []

        async def _exec(agent, role, prompt, **kwargs):
            name = role.metadata.name
            call_order.append(name)
            return _make_run_result(f"output-from-{name}"), []

        mock_exec.side_effect = _exec

        data = _make_compose_data()
        compose = ComposeDefinition.model_validate(data)

        # Build mock ComposeService objects (used by run_compose_graph_sync)
        from initrunner.compose.orchestrator import ComposeService, ComposeServiceConfig
        from initrunner.agent.schema.role import RoleDefinition

        services = {}
        for name in ["producer", "consumer"]:
            role = RoleDefinition.model_validate(_make_role_data(name))
            svc = ComposeService(
                name=name,
                role=role,
                agent=MagicMock(),
                config=ComposeServiceConfig(role=f"roles/{name}.yaml"),
            )
            services[name] = svc

        refs, entry, elapsed, timed_out = run_compose_graph_sync(
            compose, services, "hello",
            entry_service="producer",
            timeout_seconds=30,
        )

        assert not timed_out
        assert "producer" in call_order
        assert "consumer" in call_order

    @patch("initrunner.compose.graph.execute_run_async")
    def test_fan_out_parallel_timing(self, mock_exec):
        """A->[B,C]: B and C should run in parallel (~0.5s, not ~1.0s)."""
        import asyncio

        async def _exec(agent, role, prompt, **kwargs):
            await asyncio.sleep(0.4)
            return _make_run_result(f"output-{role.metadata.name}"), []

        mock_exec.side_effect = _exec

        data = _make_compose_data(
            {
                "entry": {
                    "role": "roles/entry.yaml",
                    "sink": {"type": "delegate", "target": ["svc-a", "svc-b"]},
                },
                "svc-a": {"role": "roles/a.yaml"},
                "svc-b": {"role": "roles/b.yaml"},
            }
        )
        compose = ComposeDefinition.model_validate(data)

        from initrunner.compose.orchestrator import ComposeService, ComposeServiceConfig
        from initrunner.agent.schema.role import RoleDefinition

        services = {}
        for name in ["entry", "svc-a", "svc-b"]:
            role = RoleDefinition.model_validate(_make_role_data(name))
            services[name] = ComposeService(
                name=name,
                role=role,
                agent=MagicMock(),
                config=ComposeServiceConfig(role=f"roles/{name}.yaml"),
            )

        t0 = time.monotonic()
        refs, entry, elapsed, timed_out = run_compose_graph_sync(
            compose, services, "hello",
            entry_service="entry",
            timeout_seconds=30,
        )
        wall = time.monotonic() - t0

        assert not timed_out
        # If parallel: ~0.8s (entry 0.4s + branches 0.4s concurrent)
        # If sequential: ~1.2s (entry + a + b each 0.4s)
        assert wall < 1.1, f"Expected parallel execution, got {wall:.2f}s"

    @patch("initrunner.compose.graph.execute_run_async")
    def test_callbacks_fire(self, mock_exec):
        """on_service_start and on_service_complete callbacks fire."""
        async def _exec(agent, role, prompt, **kwargs):
            return _make_run_result("done"), []

        mock_exec.side_effect = _exec

        data = _make_compose_data()
        compose = ComposeDefinition.model_validate(data)

        from initrunner.compose.orchestrator import ComposeService, ComposeServiceConfig
        from initrunner.agent.schema.role import RoleDefinition

        services = {}
        for name in ["producer", "consumer"]:
            role = RoleDefinition.model_validate(_make_role_data(name))
            services[name] = ComposeService(
                name=name,
                role=role,
                agent=MagicMock(),
                config=ComposeServiceConfig(role=f"roles/{name}.yaml"),
            )

        starts = []
        completes = []

        refs, entry, elapsed, timed_out = run_compose_graph_sync(
            compose, services, "hello",
            entry_service="producer",
            on_service_start=starts.append,
            on_service_complete=lambda name, r: completes.append(name),
        )

        assert "producer" in starts
        assert "consumer" in starts
        assert "producer" in completes
        assert "consumer" in completes

    @patch("initrunner.compose.graph.execute_run_async")
    def test_service_failure_isolation(self, mock_exec):
        """Failed service produces empty output, doesn't crash others."""
        async def _exec(agent, role, prompt, **kwargs):
            name = role.metadata.name
            if name == "svc-a":
                return _make_run_result("", success=False), []
            return _make_run_result(f"output-{name}"), []

        mock_exec.side_effect = _exec

        data = _make_compose_data(
            {
                "entry": {
                    "role": "roles/entry.yaml",
                    "sink": {"type": "delegate", "target": ["svc-a", "svc-b"]},
                },
                "svc-a": {"role": "roles/a.yaml"},
                "svc-b": {"role": "roles/b.yaml"},
            }
        )
        compose = ComposeDefinition.model_validate(data)

        from initrunner.compose.orchestrator import ComposeService, ComposeServiceConfig
        from initrunner.agent.schema.role import RoleDefinition

        services = {}
        for name in ["entry", "svc-a", "svc-b"]:
            role = RoleDefinition.model_validate(_make_role_data(name))
            services[name] = ComposeService(
                name=name,
                role=role,
                agent=MagicMock(),
                config=ComposeServiceConfig(role=f"roles/{name}.yaml"),
            )

        refs, entry, elapsed, timed_out = run_compose_graph_sync(
            compose, services, "hello",
            entry_service="entry",
            timeout_seconds=30,
        )

        # a failed but b should still have run
        assert refs["svc-b"].last_result is not None
        assert refs["svc-b"].last_result.success
        assert refs["svc-a"].error_count == 1
