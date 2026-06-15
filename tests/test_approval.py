"""Tests for human-in-the-loop approval (DeferredToolRequests)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from pydantic_ai import Agent, DeferredToolRequests
from pydantic_ai.messages import ModelRequest, ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.toolsets import ApprovalRequiredToolset

from initrunner.agent.executor_models import PendingApproval, RunResult
from initrunner.agent.schema.base import ApiVersion, Kind, ModelConfig, RoleMetadata
from initrunner.agent.schema.guardrails import Guardrails
from initrunner.agent.schema.role import AgentSpec, RoleDefinition
from initrunner.agent.schema.tools._base import ToolConfigBase, ToolPermissions
from initrunner.audit.logger import AuditLogger


def _make_role(tools: list | None = None) -> RoleDefinition:
    return RoleDefinition(
        apiVersion=ApiVersion.V1,
        kind=Kind.AGENT,
        metadata=RoleMetadata(name="demo"),
        spec=AgentSpec(
            role="You call tools.",
            model=ModelConfig(provider="openai", name="gpt-5-mini"),
            guardrails=Guardrails(timeout_seconds=30),
            tools=tools or [],
        ),
    )


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


class TestApprovalSchema:
    def test_default_is_auto(self):
        config = ToolConfigBase(type="shell")
        assert config.approval == "auto"

    def test_accepts_required(self):
        config = ToolConfigBase(type="shell", approval="required")
        assert config.approval == "required"

    def test_rejects_unknown(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            ToolConfigBase(type="shell", approval="maybe")  # type: ignore[arg-type]

    def test_permissions_coexist(self):
        config = ToolConfigBase(
            type="shell",
            approval="required",
            permissions=ToolPermissions(default="deny", allow=["command=ls *"]),
        )
        assert config.approval == "required"
        assert config.permissions is not None


# ---------------------------------------------------------------------------
# Approval toolset wiring (native ApprovalRequiredToolset)
# ---------------------------------------------------------------------------


class TestApprovalToolsetWiring:
    def test_registry_wraps_approval_required_tools(self, tmp_path):
        """build_toolsets puts ApprovalRequiredToolset outermost for
        approval: required tools, so unapproved calls defer before any
        status event fires."""
        from initrunner.agent.tools.registry import build_toolsets

        role = _make_role(tools=[{"type": "calculator", "approval": "required"}])
        toolsets = build_toolsets(role.spec.tools, role, role_dir=tmp_path)
        assert any(isinstance(ts, ApprovalRequiredToolset) for ts in toolsets)

    def test_registry_skips_wrapper_for_auto_tools(self, tmp_path):
        from initrunner.agent.tools.registry import build_toolsets

        role = _make_role(tools=[{"type": "calculator"}])
        toolsets = build_toolsets(role.spec.tools, role, role_dir=tmp_path)
        assert not any(isinstance(ts, ApprovalRequiredToolset) for ts in toolsets)


# ---------------------------------------------------------------------------
# Executor pause detection
# ---------------------------------------------------------------------------


class TestExecutorPauseDetection:
    def test_deferred_output_marks_paused(self):
        """End-to-end: a FunctionModel that returns tool calls for unapproved
        tools surfaces them via RunResult.status == "paused"."""
        from pydantic_ai.toolsets import FunctionToolset

        ts = FunctionToolset()

        @ts.tool
        def dangerous(command: str) -> str:
            return f"ran: {command}"

        wrapped = ApprovalRequiredToolset(ts)

        def fake_model(messages: list, info: AgentInfo):
            # First turn: call the tool
            return ModelResponse(
                parts=[
                    ToolCallPart(tool_name="dangerous", args={"command": "rm -rf /"}),
                ]
            )

        agent = Agent(
            FunctionModel(fake_model),
            output_type=[str, DeferredToolRequests],
            toolsets=[wrapped],
        )
        result_sync = agent.run_sync("go")
        assert isinstance(result_sync.output, DeferredToolRequests)
        assert len(result_sync.output.approvals) == 1
        assert result_sync.output.approvals[0].tool_name == "dangerous"


# ---------------------------------------------------------------------------
# Services facade: persist + resume roundtrip
# ---------------------------------------------------------------------------


class TestPersistAndResume:
    def test_persist_writes_pending_rows(self, tmp_path):
        from initrunner.services.execution import persist_paused_run

        db = tmp_path / "audit.db"
        role = _make_role()
        result = RunResult(
            run_id="r1",
            status="paused",
            pending_approvals=[
                PendingApproval(
                    tool_call_id="c1",
                    tool_name="shell",
                    arguments={"command": "ls"},
                ),
                PendingApproval(
                    tool_call_id="c2",
                    tool_name="shell",
                    arguments={"command": "cat /etc/passwd"},
                ),
            ],
        )
        with AuditLogger(db) as logger:
            persist_paused_run(logger, result, role, [], role_path=tmp_path / "r.yaml")
            pending = logger.load_pending_approvals("r1")
            assert len(pending) == 2
            assert {p.tool_call_id for p in pending} == {"c1", "c2"}
            assert all(p.agent_name == "demo" for p in pending)
            assert all(json.loads(p.arguments_json) for p in pending)

    def test_load_pending_state_roundtrip(self, tmp_path):
        from pydantic_ai.messages import ModelMessage, ModelMessagesTypeAdapter

        from initrunner.services.execution import load_pending_state, persist_paused_run

        db = tmp_path / "audit.db"
        role = _make_role()
        # Build a minimal but valid message history
        history: list[ModelMessage] = [ModelRequest.user_text_prompt("hello")]
        result = RunResult(
            run_id="r1",
            status="paused",
            pending_approvals=[
                PendingApproval(tool_call_id="c1", tool_name="shell", arguments={"x": 1}),
            ],
        )
        with AuditLogger(db) as logger:
            persist_paused_run(logger, result, role, history)
            state = load_pending_state(logger, "r1")
            assert state is not None
            recovered_history, rows = state
            assert len(rows) == 1
            assert rows[0].tool_call_id == "c1"
            # Round-trip the history through the adapter to confirm same semantics
            assert ModelMessagesTypeAdapter.dump_json(
                recovered_history
            ) == ModelMessagesTypeAdapter.dump_json(history)

    def test_load_pending_state_returns_none_when_resolved(self, tmp_path):
        from initrunner.services.execution import load_pending_state, persist_paused_run

        db = tmp_path / "audit.db"
        role = _make_role()
        result = RunResult(
            run_id="r1",
            status="paused",
            pending_approvals=[
                PendingApproval(tool_call_id="c1", tool_name="shell", arguments={}),
            ],
        )
        with AuditLogger(db) as logger:
            persist_paused_run(logger, result, role, [])
            logger.resolve_pending_approval(run_id="r1", tool_call_id="c1", decision=True)
            assert load_pending_state(logger, "r1") is None


# ---------------------------------------------------------------------------
# Loader widens output_type when a tool requires approval
# ---------------------------------------------------------------------------


class TestLoaderWidensOutputType:
    def _stub_loader(self, monkeypatch, tools):
        """Shared monkeypatching so build_agent doesn't hit real toolsets."""
        from initrunner.agent import loader

        captured: dict = {}

        def fake_create_agent(role, instructions, toolsets, output_type, **kwargs):
            captured["output_type"] = output_type
            return MagicMock(spec=Agent)

        monkeypatch.setattr(loader, "_create_agent", fake_create_agent)
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        fake_auto = MagicMock(extra_toolsets=[], prompt_addendum="", prepare_tools=None)
        monkeypatch.setattr(loader, "_build_auto_tools", lambda *a, **kw: fake_auto)
        monkeypatch.setattr(loader, "_validate_provider", lambda *a, **kw: None)
        monkeypatch.setattr(loader, "_validate_reasoning", lambda *a, **kw: None)
        monkeypatch.setattr(
            loader,
            "_resolve_skills_and_merge",
            lambda *a, **kw: ("You call tools.", tools, []),
        )
        # Stub the real toolset builder so concrete tool builders aren't
        # invoked with a bare ToolConfigBase.
        import initrunner.agent.tools as tools_pkg

        monkeypatch.setattr(tools_pkg, "build_toolsets", lambda *a, **kw: [])
        return loader, captured

    def test_widens_when_approval_required(self, monkeypatch):
        tools = [ToolConfigBase(type="http", approval="required")]
        role = _make_role(tools=tools)
        loader, captured = self._stub_loader(monkeypatch, tools)
        loader.build_agent(role)
        assert isinstance(captured["output_type"], list)
        assert DeferredToolRequests in captured["output_type"]

    def test_single_output_type_when_no_approval(self, monkeypatch):
        tools = [ToolConfigBase(type="http")]  # approval defaults to auto
        role = _make_role(tools=tools)
        loader, captured = self._stub_loader(monkeypatch, tools)
        loader.build_agent(role)
        assert not isinstance(captured["output_type"], list)


# ---------------------------------------------------------------------------
# API server: paused response and resume route
# ---------------------------------------------------------------------------


class TestApprovalsApi:
    def _role(self):
        return _make_role()

    def _client(self, tmp_path):
        from starlette.testclient import TestClient

        from initrunner.server.app import create_app

        role = self._role()
        agent = MagicMock()
        audit = AuditLogger(tmp_path / "audit.db")
        app = create_app(agent, role, audit_logger=audit, role_path=tmp_path / "role.yaml")
        return TestClient(app), audit, role

    @patch("initrunner.server.app.execute_run_sync")
    def test_non_stream_paused(self, mock_execute, tmp_path):
        """A paused run returns 200 with pending_approvals and persists state."""
        mock_execute.return_value = (
            RunResult(
                run_id="r1",
                status="paused",
                pending_approvals=[
                    PendingApproval(
                        tool_call_id="c1",
                        tool_name="shell",
                        arguments={"command": "rm -rf /"},
                    )
                ],
            ),
            [ModelRequest.user_text_prompt("hi")],
        )
        client, audit, _role = self._client(tmp_path)
        try:
            resp = client.post(
                "/v1/chat/completions",
                json={"model": "demo", "messages": [{"role": "user", "content": "hi"}]},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["choices"][0]["finish_reason"] == "tool_calls_pending_approval"
            assert data["run_id"] == "r1"
            assert data["pending_approvals"][0]["tool_call_id"] == "c1"
            # Persisted
            assert len(audit.load_pending_approvals("r1")) == 1
        finally:
            audit.close()

    def test_resume_route_404_on_unknown_run(self, tmp_path):
        client, audit, _ = self._client(tmp_path)
        try:
            resp = client.post("/v1/approvals/does-not-exist", json={"c1": True})
            assert resp.status_code == 404
        finally:
            audit.close()

    def test_resume_route_rejects_non_bool_body(self, tmp_path):
        client, audit, _ = self._client(tmp_path)
        try:
            resp = client.post("/v1/approvals/r1", json={"c1": "yes"})
            assert resp.status_code == 400
        finally:
            audit.close()
