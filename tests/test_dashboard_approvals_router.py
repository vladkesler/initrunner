"""Tests for the dashboard approvals router + streaming paused payload."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

pytest.importorskip("fastapi", reason="dashboard extras not installed")

from fastapi.testclient import TestClient  # type: ignore[import-not-found]
from pydantic_ai.messages import ModelMessage, ModelMessagesTypeAdapter, ModelRequest

from initrunner.agent.executor_models import PendingApproval, RunResult
from initrunner.agent.schema.base import ApiVersion, Kind, ModelConfig, RoleMetadata
from initrunner.agent.schema.guardrails import Guardrails
from initrunner.agent.schema.role import AgentSpec, RoleDefinition
from initrunner.audit.logger import AuditLogger
from initrunner.dashboard.app import create_app
from initrunner.dashboard.config import DashboardSettings
from initrunner.dashboard.streaming import _build_result_payload
from initrunner.services.execution import persist_paused_run


def _make_role(name: str = "approval-demo") -> RoleDefinition:
    return RoleDefinition(
        apiVersion=ApiVersion.V1,
        kind=Kind.AGENT,
        metadata=RoleMetadata(name=name),
        spec=AgentSpec(
            role="You call tools.",
            model=ModelConfig(provider="openai", name="gpt-5-mini"),
            guardrails=Guardrails(),
        ),
    )


@pytest.fixture()
def audit_db(tmp_path, monkeypatch):
    db_path = tmp_path / "audit.db"
    monkeypatch.setattr(
        "initrunner.config.get_audit_db_path",
        lambda: db_path,
    )
    return db_path


@pytest.fixture()
def client(audit_db):
    settings = DashboardSettings()
    app = create_app(settings)
    return TestClient(app)


def _seed_paused_run(
    db_path: Path,
    *,
    run_id: str,
    tool_call_ids: list[str],
    role_path: Path | None = None,
) -> None:
    """Write pending-approval rows directly so tests don't need a live agent."""
    role = _make_role()
    result = RunResult(
        run_id=run_id,
        status="paused",
        pending_approvals=[
            PendingApproval(
                tool_call_id=cid,
                tool_name="write_file",
                arguments={"path": f"/tmp/{cid}.txt", "content": "hello"},
            )
            for cid in tool_call_ids
        ],
    )
    history: list[ModelMessage] = [ModelRequest.user_text_prompt("please write the file")]
    with AuditLogger(db_path) as logger:
        persist_paused_run(logger, result, role, history, role_path=role_path)


# ---------------------------------------------------------------------------
# Streaming payload (G1 — the only required backend change)
# ---------------------------------------------------------------------------


class TestStreamingPausedPayload:
    def test_payload_surfaces_paused_status_and_calls(self):
        role = _make_role()
        history: list[ModelMessage] = [ModelRequest.user_text_prompt("write a file")]
        result = RunResult(
            run_id="r1",
            status="paused",
            pending_approvals=[
                PendingApproval(
                    tool_call_id="c1",
                    tool_name="write_file",
                    arguments={"path": "/tmp/x.txt"},
                )
            ],
        )
        payload = _build_result_payload(result, history, role)
        assert payload["status"] == "paused"
        assert payload["pending_approvals"] == [
            {
                "tool_call_id": "c1",
                "tool_name": "write_file",
                "arguments": {"path": "/tmp/x.txt"},
            }
        ]
        # Message history is serialized even on pause so the resume path can use it.
        assert payload["message_history"] is not None

    def test_payload_keeps_done_for_normal_runs(self):
        role = _make_role()
        history: list[ModelMessage] = [ModelRequest.user_text_prompt("hi")]
        result = RunResult(run_id="r2", output="ok", success=True, status="done")
        payload = _build_result_payload(result, history, role)
        assert payload["status"] == "done"
        assert payload["pending_approvals"] == []


# ---------------------------------------------------------------------------
# GET /api/approvals/pending
# ---------------------------------------------------------------------------


class TestListPending:
    def test_empty_queue(self, client, audit_db):
        # Touch the DB to create the table
        AuditLogger(audit_db).close()
        resp = client.get("/api/approvals/pending")
        assert resp.status_code == 200
        body = resp.json()
        assert body == {"runs": [], "count": 0}

    def test_count_only_returns_just_count(self, client, audit_db, tmp_path):
        _seed_paused_run(
            audit_db,
            run_id="r1",
            tool_call_ids=["c1", "c2"],
            role_path=tmp_path / "role.yaml",
        )
        resp = client.get("/api/approvals/pending?count_only=1")
        assert resp.status_code == 200
        assert resp.json() == {"count": 2}

    def test_groups_by_run(self, client, audit_db, tmp_path):
        role_path = tmp_path / "role.yaml"
        _seed_paused_run(audit_db, run_id="r1", tool_call_ids=["c1", "c2"], role_path=role_path)
        _seed_paused_run(audit_db, run_id="r2", tool_call_ids=["c3"], role_path=role_path)
        resp = client.get("/api/approvals/pending")
        assert resp.status_code == 200
        body = resp.json()
        assert body["count"] == 3
        assert len(body["runs"]) == 2
        run_ids = {r["run_id"] for r in body["runs"]}
        assert run_ids == {"r1", "r2"}
        r1 = next(r for r in body["runs"] if r["run_id"] == "r1")
        assert {c["tool_call_id"] for c in r1["calls"]} == {"c1", "c2"}
        assert r1["originating_prompt"] == "please write the file"
        assert r1["agent_name"] == "approval-demo"


# ---------------------------------------------------------------------------
# GET /api/approvals/{run_id}
# ---------------------------------------------------------------------------


class TestGetRun:
    def test_returns_detail_for_known_run(self, client, audit_db, tmp_path):
        _seed_paused_run(
            audit_db,
            run_id="r1",
            tool_call_ids=["c1"],
            role_path=tmp_path / "role.yaml",
        )
        resp = client.get("/api/approvals/r1")
        assert resp.status_code == 200
        body = resp.json()
        assert body["run_id"] == "r1"
        assert len(body["calls"]) == 1
        assert body["calls"][0]["tool_name"] == "write_file"

    def test_404_on_unknown_run(self, client, audit_db):
        AuditLogger(audit_db).close()
        resp = client.get("/api/approvals/does-not-exist")
        assert resp.status_code == 404

    def test_404_when_all_resolved(self, client, audit_db, tmp_path):
        _seed_paused_run(
            audit_db,
            run_id="r1",
            tool_call_ids=["c1"],
            role_path=tmp_path / "role.yaml",
        )
        with AuditLogger(audit_db) as logger:
            logger.resolve_pending_approval(run_id="r1", tool_call_id="c1", decision=True)
        resp = client.get("/api/approvals/r1")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /api/approvals/{run_id}
# ---------------------------------------------------------------------------


class TestResolveRun:
    def test_empty_body_rejected(self, client, audit_db, tmp_path):
        _seed_paused_run(audit_db, run_id="r1", tool_call_ids=["c1"], role_path=tmp_path / "r.yaml")
        resp = client.post("/api/approvals/r1", json={"decisions": {}})
        assert resp.status_code == 400

    def test_missing_decisions_field_rejected(self, client, audit_db, tmp_path):
        _seed_paused_run(audit_db, run_id="r1", tool_call_ids=["c1"], role_path=tmp_path / "r.yaml")
        resp = client.post("/api/approvals/r1", json={})
        # Pydantic returns 422 when the required ``decisions`` field is missing.
        assert resp.status_code == 422

    def test_non_dict_decisions_rejected(self, client, audit_db, tmp_path):
        _seed_paused_run(audit_db, run_id="r1", tool_call_ids=["c1"], role_path=tmp_path / "r.yaml")
        resp = client.post("/api/approvals/r1", json={"decisions": "not-a-dict"})
        assert resp.status_code == 422

    def test_404_on_unknown_run(self, client, audit_db):
        AuditLogger(audit_db).close()
        resp = client.post("/api/approvals/nope", json={"decisions": {"c1": True}})
        assert resp.status_code == 404

    def test_410_when_role_file_missing(self, client, audit_db, tmp_path):
        # Seed with a role_path that doesn't exist on disk
        missing = tmp_path / "missing.yaml"
        _seed_paused_run(audit_db, run_id="r1", tool_call_ids=["c1"], role_path=missing)
        resp = client.post("/api/approvals/r1", json={"decisions": {"c1": True}})
        assert resp.status_code == 410
        assert "no longer exists" in resp.json()["detail"]

    def test_successful_resume(self, client, audit_db, tmp_path):
        role_path = tmp_path / "role.yaml"
        _seed_paused_run(audit_db, run_id="r1", tool_call_ids=["c1"], role_path=role_path)
        role_path.write_text("stub")  # existence check only — build is mocked

        # Stub the agent build + resume so we don't hit a real model.
        def fake_build(_path):
            return _make_role(), object()

        def fake_resume(agent, role, run_id, approvals, **kwargs):
            result = RunResult(
                run_id=run_id,
                output="did the thing",
                success=True,
                status="done",
                tokens_in=10,
                tokens_out=5,
                total_tokens=15,
            )
            return result, []

        with (
            patch(
                "initrunner.services.execution.build_agent_sync",
                side_effect=fake_build,
            ),
            patch(
                "initrunner.services.execution.resume_run_sync",
                side_effect=fake_resume,
            ),
        ):
            resp = client.post(
                "/api/approvals/r1",
                json={"decisions": {"c1": True}, "resolved_by": "tester"},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "done"
        assert body["success"] is True
        assert body["output"] == "did the thing"
        assert body["pending_approvals"] == []
        # Message history round-trips so the client can pass it into the next turn
        assert body["message_history"] is not None
        ModelMessagesTypeAdapter.validate_json(body["message_history"])

    def test_re_pause_surfaces_new_calls(self, client, audit_db, tmp_path):
        role_path = tmp_path / "role.yaml"
        _seed_paused_run(audit_db, run_id="r1", tool_call_ids=["c1"], role_path=role_path)
        role_path.write_text("stub")

        def fake_build(_path):
            return _make_role(), object()

        def fake_resume(agent, role, run_id, approvals, **kwargs):
            result = RunResult(
                run_id=run_id,
                status="paused",
                success=True,
                pending_approvals=[
                    PendingApproval(
                        tool_call_id="c2",
                        tool_name="write_file",
                        arguments={"path": "/tmp/y.txt"},
                    )
                ],
            )
            return result, []

        with (
            patch(
                "initrunner.services.execution.build_agent_sync",
                side_effect=fake_build,
            ),
            patch(
                "initrunner.services.execution.resume_run_sync",
                side_effect=fake_resume,
            ),
        ):
            resp = client.post("/api/approvals/r1", json={"decisions": {"c1": True}})

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "paused"
        assert len(body["pending_approvals"]) == 1
        assert body["pending_approvals"][0]["tool_call_id"] == "c2"
