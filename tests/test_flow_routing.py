"""Flow keyword/sense routing: the chosen target runs, and the decision is recorded."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from initrunner.agent.executor import RunResult
from initrunner.agent.schema.role import RoleDefinition
from initrunner.flow.graph import run_flow_graph_sync
from initrunner.flow.orchestrator import FlowAgentConfig, FlowMember
from initrunner.flow.schema import FlowDefinition

_ROLES = {
    "triage": ("Reads a customer message and hands it on", []),
    "billing": ("Handles charges, refunds and invoices", ["billing", "refunds"]),
    "shipping": ("Handles delivery, tracking and lost parcels", ["shipping", "delivery"]),
}


def _role(name: str) -> RoleDefinition:
    description, tags = _ROLES[name]
    return RoleDefinition.model_validate(
        {
            "apiVersion": "initrunner/v1",
            "kind": "Agent",
            "metadata": {"name": name, "description": description, "tags": tags},
            "spec": {
                "role": f"You are {name}.",
                "model": {"provider": "openai", "name": "gpt-5-mini"},
            },
        }
    )


def _flow(strategy: str) -> FlowDefinition:
    return FlowDefinition.model_validate(
        {
            "apiVersion": "initrunner/v1",
            "kind": "Flow",
            "metadata": {"name": "support-desk"},
            "spec": {
                "agents": {
                    "triage": {
                        "role": "roles/triage.yaml",
                        "sink": {
                            "type": "delegate",
                            "target": ["billing", "shipping"],
                            "strategy": strategy,
                        },
                    },
                    "billing": {"role": "roles/billing.yaml"},
                    "shipping": {"role": "roles/shipping.yaml"},
                }
            },
        }
    )


def _run(strategy: str, triage_output: str, audit_logger) -> list[str]:
    ran: list[str] = []

    async def _exec(agent, role, prompt, **kwargs):
        ran.append(role.metadata.name)
        result = RunResult(run_id=f"run-{role.metadata.name}")
        result.output = triage_output if role.metadata.name == "triage" else "handled"
        result.success = True
        return result, []

    services = {
        name: FlowMember(
            name=name,
            role=_role(name),
            agent=MagicMock(),
            config=FlowAgentConfig(role=f"roles/{name}.yaml"),
        )
        for name in _ROLES
    }
    with patch("initrunner.flow.graph.execute_run_async", side_effect=_exec):
        run_flow_graph_sync(
            _flow(strategy),
            services,
            "hello",
            entry_service="triage",
            timeout_seconds=30,
            audit_logger=audit_logger,
            flow_run_id="flow-run-1",
        )
    return ran


class TestFlowRouting:
    def test_keyword_routes_and_records_the_decision(self):
        audit = MagicMock()
        ran = _run("keyword", "customer wants refunds for billing charges", audit)

        assert ran == ["triage", "billing"]
        kwargs = audit.log_delegate_event.call_args.kwargs
        assert kwargs["source_service"] == "triage"
        assert kwargs["target_service"] == "billing"
        assert kwargs["status"] == "routed"
        assert kwargs["reason"].startswith("keyword ")
        # The dashboard Events tab only shows rows whose compose_name is the flow.
        assert kwargs["compose_name"] == "support-desk"
        assert kwargs["source_run_id"] == "flow-run-1"

    def test_keyword_strategy_never_asks_jev(self, monkeypatch):
        import initrunner.jev as jev

        asked = []
        monkeypatch.setattr(jev, "is_configured", lambda: True)
        monkeypatch.setattr(jev, "ask", lambda *a: asked.append(a))
        _run("keyword", "customer wants refunds for billing charges", MagicMock())
        assert asked == []

    def test_sense_uses_jev_when_configured(self, monkeypatch):
        import initrunner.jev as jev
        from initrunner.jev import ChoiceResult, Judgment

        probabilities = {"billing": 0.05, "shipping": 0.9, "none_of_these": 0.05}
        monkeypatch.setattr(jev, "is_configured", lambda: True)
        monkeypatch.setattr(
            jev,
            "ask",
            lambda state, questions: Judgment(
                choices={
                    "agent": ChoiceResult(
                        choice="shipping", confidence=0.9, probabilities=probabilities
                    )
                },
                model="jev-1.13.0",
            ),
        )
        audit = MagicMock()
        # Keyword scoring alone would pick billing here; Jev's answer must win.
        ran = _run("sense", "billing question about my refund", audit)

        assert ran == ["triage", "shipping"]
        assert audit.log_delegate_event.call_args.kwargs["reason"] == "jev 0.90"

    @pytest.mark.parametrize("strategy", ["keyword", "sense"])
    def test_no_audit_logger_is_fine(self, strategy):
        assert _run(strategy, "refunds for billing charges", None)[0] == "triage"
