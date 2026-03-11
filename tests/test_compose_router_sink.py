"""Tests for the sense-aware router sink."""

from __future__ import annotations

import queue
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from initrunner.compose.delegate_sink import DelegateEvent, DelegateSink
from initrunner.compose.router_sink import RouterSink
from initrunner.services.role_selector import RoleCandidate, SelectionResult
from initrunner.sinks.base import SinkPayload


def _make_payload(**overrides) -> SinkPayload:
    defaults = {
        "agent_name": "test-agent",
        "run_id": "abc123",
        "prompt": "hello",
        "output": "research about machine learning",
        "success": True,
        "error": None,
        "tokens_in": 10,
        "tokens_out": 20,
        "duration_ms": 100,
        "model": "gpt-5-mini",
        "provider": "openai",
        "trigger_type": None,
        "trigger_metadata": {},
        "timestamp": "2025-01-01T00:00:00+00:00",
    }
    defaults.update(overrides)
    return SinkPayload(**defaults)  # type: ignore[arg-type]


def _make_candidates() -> list[RoleCandidate]:
    return [
        RoleCandidate(
            path=Path("roles/researcher.yaml"),
            name="researcher",
            description="Research topics and gather information",
            tags=["research", "analysis"],
        ),
        RoleCandidate(
            path=Path("roles/responder.yaml"),
            name="responder",
            description="Respond to user queries directly",
            tags=["response", "chat"],
        ),
        RoleCandidate(
            path=Path("roles/escalator.yaml"),
            name="escalator",
            description="Escalate complex issues to humans",
            tags=["escalation", "support"],
        ),
    ]


def _make_delegate_sinks() -> dict[str, DelegateSink]:
    sinks = {}
    for name in ["researcher", "responder", "escalator"]:
        q: queue.Queue[DelegateEvent] = queue.Queue()
        sinks[name] = DelegateSink(source_service="triager", target_service=name, target_queue=q)
    return sinks


class TestRouterSinkKeyword:
    def test_routes_to_best_keyword_match(self):
        sinks = _make_delegate_sinks()
        candidates = _make_candidates()
        router = RouterSink(sinks, candidates, strategy="keyword")

        payload = _make_payload(output="research about machine learning")
        router.send(payload)

        # researcher sink should have received the message
        assert sinks["researcher"]._target_queue.qsize() == 1
        assert sinks["responder"]._target_queue.qsize() == 0
        assert sinks["escalator"]._target_queue.qsize() == 0

    def test_routes_based_on_tags(self):
        sinks = _make_delegate_sinks()
        candidates = _make_candidates()
        router = RouterSink(sinks, candidates, strategy="keyword")

        payload = _make_payload(output="this needs escalation to a human")
        router.send(payload)

        assert sinks["escalator"]._target_queue.qsize() == 1
        assert sinks["researcher"]._target_queue.qsize() == 0
        assert sinks["responder"]._target_queue.qsize() == 0

    def test_does_not_call_llm_in_keyword_mode(self):
        sinks = _make_delegate_sinks()
        candidates = _make_candidates()
        router = RouterSink(sinks, candidates, strategy="keyword")

        with patch("initrunner.services.role_selector._llm_select") as mock_llm:
            payload = _make_payload(output="something vague")
            router.send(payload)
            mock_llm.assert_not_called()

    def test_audit_reason_in_metadata(self):
        sinks = _make_delegate_sinks()
        candidates = _make_candidates()
        router = RouterSink(sinks, candidates, strategy="keyword")

        payload = _make_payload(output="research about machine learning")
        router.send(payload)

        assert "_compose_route_reason" in payload.trigger_metadata
        reason = payload.trigger_metadata["_compose_route_reason"]
        assert "sense:" in reason
        assert "selected=researcher" in reason


class TestRouterSinkSense:
    def test_uses_llm_when_ambiguous(self):
        sinks = _make_delegate_sinks()
        candidates = _make_candidates()
        router = RouterSink(sinks, candidates, strategy="sense")

        # Mock select_candidate_sync to simulate LLM tiebreak
        mock_result = SelectionResult(
            candidate=candidates[1],  # responder
            method="llm",
            top_score=0.3,
            gap=0.05,
            used_llm=True,
        )
        with patch(
            "initrunner.compose.router_sink.select_candidate_sync", return_value=mock_result
        ):
            payload = _make_payload(output="something ambiguous")
            router.send(payload)

        assert sinks["responder"]._target_queue.qsize() == 1

    def test_llm_failure_falls_back_to_keyword(self):
        sinks = _make_delegate_sinks()
        candidates = _make_candidates()
        router = RouterSink(sinks, candidates, strategy="sense")

        # The real select_candidate_sync should handle LLM failure internally
        # and return a fallback result
        payload = _make_payload(output="research analysis of data")
        with patch(
            "initrunner.services.role_selector._llm_select",
            side_effect=RuntimeError("API down"),
        ):
            router.send(payload)

        # Should still route somewhere (fallback picks top keyword scorer)
        total = sum(s._target_queue.qsize() for s in sinks.values())
        assert total == 1


class TestRouterSinkDualScoring:
    def test_falls_back_to_original_prompt_when_output_inconclusive(self):
        sinks = _make_delegate_sinks()
        candidates = _make_candidates()
        router = RouterSink(sinks, candidates, strategy="keyword")

        # Output is vague, but the original prompt clearly indicates research
        payload = _make_payload(
            output="here are my thoughts on the matter",
            trigger_metadata={
                "_compose_original_prompt": "research the latest AI papers",
            },
        )

        router.send(payload)

        assert sinks["researcher"]._target_queue.qsize() == 1

    def test_uses_output_when_output_is_conclusive(self):
        sinks = _make_delegate_sinks()
        candidates = _make_candidates()
        router = RouterSink(sinks, candidates, strategy="keyword")

        # Output clearly indicates escalation
        payload = _make_payload(
            output="escalation needed for this support issue",
            trigger_metadata={
                "_compose_original_prompt": "research something",
            },
        )

        router.send(payload)

        assert sinks["escalator"]._target_queue.qsize() == 1


class TestRouterSinkEdgeCases:
    def test_single_target_gets_all_messages(self):
        """With only one target, routing always goes there."""
        q: queue.Queue[DelegateEvent] = queue.Queue()
        sole_sink = DelegateSink("triager", "researcher", q)
        sinks = {"researcher": sole_sink}
        candidates = [
            RoleCandidate(
                path=Path("roles/researcher.yaml"),
                name="researcher",
                description="Research topics",
                tags=["research"],
            ),
        ]
        router = RouterSink(sinks, candidates, strategy="keyword")

        payload = _make_payload(output="something completely unrelated")
        router.send(payload)

        assert q.qsize() == 1

    def test_close_delegates_to_all_sinks(self):
        sinks = _make_delegate_sinks()
        candidates = _make_candidates()
        router = RouterSink(sinks, candidates, strategy="keyword")

        router.close()

        # All flush_stop events should be set (DelegateSink.close sets them)
        for sink in sinks.values():
            assert sink._flush_stop.is_set()

    def test_error_in_routing_falls_back_to_first_sink(self):
        sinks = _make_delegate_sinks()
        candidates = _make_candidates()
        router = RouterSink(sinks, candidates, strategy="keyword")

        with patch(
            "initrunner.compose.router_sink.select_candidate_sync",
            side_effect=RuntimeError("scoring crashed"),
        ):
            payload = _make_payload(output="anything")
            router.send(payload)

        # Should fall back to first sink
        first_name = next(iter(sinks))
        assert sinks[first_name]._target_queue.qsize() == 1

    def test_failed_payload_still_routed(self):
        """Router routes the payload; DelegateSink's own filter handles success=False."""
        sinks = _make_delegate_sinks()
        candidates = _make_candidates()
        router = RouterSink(sinks, candidates, strategy="keyword")

        payload = _make_payload(success=False, error="upstream failed", output="research data")
        router.send(payload)

        # DelegateSink filters failed payloads, so nothing enqueued
        total = sum(s._target_queue.qsize() for s in sinks.values())
        assert total == 0
        # But one sink should have incremented its filtered count
        total_filtered = sum(s.filtered_count for s in sinks.values())
        assert total_filtered == 1


class TestRouterSinkWithOrchestrator:
    @patch("initrunner.compose.orchestrator.load_and_build")
    def test_wire_delegates_creates_router_for_sense_strategy(self, mock_load):
        from initrunner.agent.schema.role import RoleDefinition
        from initrunner.compose.orchestrator import ComposeOrchestrator
        from initrunner.compose.schema import ComposeDefinition

        role_data = {
            "apiVersion": "initrunner/v1",
            "kind": "Agent",
            "metadata": {"name": "test-agent", "description": "test desc", "tags": ["test"]},
            "spec": {
                "role": "You are a test agent.",
                "model": {"provider": "openai", "name": "gpt-5-mini"},
            },
        }
        role = RoleDefinition.model_validate(role_data)
        mock_load.return_value = (role, MagicMock())

        compose_data = {
            "apiVersion": "initrunner/v1",
            "kind": "Compose",
            "metadata": {"name": "router-test"},
            "spec": {
                "services": {
                    "triager": {
                        "role": "roles/triager.yaml",
                        "sink": {
                            "type": "delegate",
                            "strategy": "sense",
                            "target": ["researcher", "responder"],
                        },
                    },
                    "researcher": {"role": "roles/researcher.yaml"},
                    "responder": {"role": "roles/responder.yaml"},
                }
            },
        }

        compose = ComposeDefinition.model_validate(compose_data)
        orch = ComposeOrchestrator(compose, Path("."))
        orch._build_services()
        orch._wire_delegates()

        # Triager should have a RouterSink, not individual DelegateSinks
        triager = orch._services["triager"]
        assert triager._sink_dispatcher.count == 1
        assert isinstance(triager._sink_dispatcher._sinks[0], RouterSink)

        # Router sinks tracked for lifecycle
        assert len(orch._router_sinks) == 1
        # Individual delegate sinks not in _delegate_sinks (managed by router)
        assert len(orch._delegate_sinks) == 0

    @patch("initrunner.compose.orchestrator.load_and_build")
    def test_wire_delegates_fanout_for_all_strategy(self, mock_load):
        from initrunner.agent.schema.role import RoleDefinition
        from initrunner.compose.orchestrator import ComposeOrchestrator
        from initrunner.compose.schema import ComposeDefinition

        role_data = {
            "apiVersion": "initrunner/v1",
            "kind": "Agent",
            "metadata": {"name": "test-agent", "description": "test"},
            "spec": {
                "role": "You are a test agent.",
                "model": {"provider": "openai", "name": "gpt-5-mini"},
            },
        }
        role = RoleDefinition.model_validate(role_data)
        mock_load.return_value = (role, MagicMock())

        compose_data = {
            "apiVersion": "initrunner/v1",
            "kind": "Compose",
            "metadata": {"name": "fanout-test"},
            "spec": {
                "services": {
                    "producer": {
                        "role": "roles/producer.yaml",
                        "sink": {
                            "type": "delegate",
                            "target": ["a", "b"],
                        },
                    },
                    "a": {"role": "roles/a.yaml"},
                    "b": {"role": "roles/b.yaml"},
                }
            },
        }

        compose = ComposeDefinition.model_validate(compose_data)
        orch = ComposeOrchestrator(compose, Path("."))
        orch._build_services()
        orch._wire_delegates()

        # Default strategy=all — individual sinks, no router
        producer = orch._services["producer"]
        assert producer._sink_dispatcher.count == 2
        assert all(isinstance(s, DelegateSink) for s in producer._sink_dispatcher._sinks)
        assert len(orch._delegate_sinks) == 2
        assert len(orch._router_sinks) == 0

    @patch("initrunner.compose.orchestrator.load_and_build")
    def test_delegate_health_includes_router_sinks(self, mock_load):
        from initrunner.agent.schema.role import RoleDefinition
        from initrunner.compose.orchestrator import ComposeOrchestrator
        from initrunner.compose.schema import ComposeDefinition

        role_data = {
            "apiVersion": "initrunner/v1",
            "kind": "Agent",
            "metadata": {"name": "test-agent", "description": "test desc", "tags": ["test"]},
            "spec": {
                "role": "You are a test agent.",
                "model": {"provider": "openai", "name": "gpt-5-mini"},
            },
        }
        role = RoleDefinition.model_validate(role_data)
        mock_load.return_value = (role, MagicMock())

        compose_data = {
            "apiVersion": "initrunner/v1",
            "kind": "Compose",
            "metadata": {"name": "health-test"},
            "spec": {
                "services": {
                    "triager": {
                        "role": "roles/triager.yaml",
                        "sink": {
                            "type": "delegate",
                            "strategy": "keyword",
                            "target": ["a", "b"],
                        },
                    },
                    "a": {"role": "roles/a.yaml"},
                    "b": {"role": "roles/b.yaml"},
                }
            },
        }

        compose = ComposeDefinition.model_validate(compose_data)
        orch = ComposeOrchestrator(compose, Path("."))
        orch._build_services()
        orch._wire_delegates()

        health = orch.delegate_health()
        assert len(health) == 2
        targets = {h["target"] for h in health}
        assert targets == {"a", "b"}


class TestRouterSinkSchemaIntegration:
    def test_strategy_defaults_to_all(self):
        from initrunner.compose.schema import DelegateSinkConfig

        config = DelegateSinkConfig(target=["a", "b"])
        assert config.strategy == "all"

    def test_strategy_keyword(self):
        from initrunner.compose.schema import DelegateSinkConfig

        config = DelegateSinkConfig(target=["a", "b"], strategy="keyword")
        assert config.strategy == "keyword"

    def test_strategy_sense(self):
        from initrunner.compose.schema import DelegateSinkConfig

        config = DelegateSinkConfig(target=["a", "b"], strategy="sense")
        assert config.strategy == "sense"

    def test_strategy_invalid_rejected(self):
        from pydantic import ValidationError

        from initrunner.compose.schema import DelegateSinkConfig

        with pytest.raises(ValidationError):
            DelegateSinkConfig(target=["a", "b"], strategy="round_robin")  # type: ignore[arg-type]

    def test_summary_with_strategy(self):
        from initrunner.compose.schema import DelegateSinkConfig

        config = DelegateSinkConfig(target=["a", "b"], strategy="sense")
        assert config.summary() == "delegate: a, b [sense]"

    def test_summary_without_strategy(self):
        from initrunner.compose.schema import DelegateSinkConfig

        config = DelegateSinkConfig(target=["a", "b"])
        assert config.summary() == "delegate: a, b"
