"""Serving several agents from one process."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from starlette.testclient import TestClient

from initrunner.agent.executor import RunResult
from initrunner.agent.schema.base import ApiVersion, Kind, ModelConfig, RoleMetadata
from initrunner.agent.schema.guardrails import Guardrails
from initrunner.agent.schema.role import AgentSpec, RoleDefinition
from initrunner.agent.schema.security import SecurityPolicy
from initrunner.server.app import ServedMember, create_multi_app


def _role(name: str) -> RoleDefinition:
    return RoleDefinition(
        apiVersion=ApiVersion.V1,
        kind=Kind.AGENT,
        metadata=RoleMetadata(name=f"{name}-agent"),
        spec=AgentSpec(
            role="You are a test.",
            model=ModelConfig(provider="openai", name="gpt-5-mini"),
            guardrails=Guardrails(),
        ),
    )


def _client(keys=("intake", "writer"), **kwargs) -> TestClient:
    members = {key: ServedMember(key=key, role=_role(key), agent=MagicMock()) for key in keys}
    app = create_multi_app(members, security=SecurityPolicy(), **kwargs)
    return TestClient(app)


def _ok(output: str = "hi"):
    return RunResult(run_id="r", output=output, success=True), []


class TestModelListing:
    def test_lists_every_member(self):
        resp = _client().get("/v1/models")

        assert resp.status_code == 200
        assert [m["id"] for m in resp.json()["data"]] == ["intake", "writer"]


class TestRouting:
    @patch("initrunner.server.app.execute_run_sync")
    def test_model_selects_the_agent(self, mock_exec):
        mock_exec.return_value = _ok("triaged")
        client = _client()

        resp = client.post(
            "/v1/chat/completions",
            json={"model": "writer", "messages": [{"role": "user", "content": "hi"}]},
        )

        assert resp.status_code == 200
        assert resp.json()["model"] == "writer"
        assert mock_exec.call_args.args[1].metadata.name == "writer-agent"

    def test_missing_model_lists_the_agents(self):
        resp = _client().post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "hi"}]},
        )

        assert resp.status_code == 400
        message = resp.json()["error"]["message"]
        assert "intake, writer" in message

    def test_unknown_model_lists_the_agents(self):
        resp = _client().post(
            "/v1/chat/completions",
            json={"model": "nope", "messages": [{"role": "user", "content": "hi"}]},
        )

        assert resp.status_code == 400
        assert "unknown model 'nope'" in resp.json()["error"]["message"]

    @patch("initrunner.server.app.execute_run_sync")
    def test_single_agent_server_still_ignores_model(self, mock_exec):
        """The long-standing single-agent behaviour is unchanged."""
        mock_exec.return_value = _ok()
        client = _client(keys=("solo",))

        resp = client.post(
            "/v1/chat/completions",
            json={"model": "whatever", "messages": [{"role": "user", "content": "hi"}]},
        )

        assert resp.status_code == 200


class TestConversationIsolation:
    @patch("initrunner.server.app.execute_run_sync")
    def test_history_does_not_cross_agents(self, mock_exec):
        """One conversation id reused across agents must not share history."""
        mock_exec.return_value = _ok()
        client = _client()
        headers = {"X-Conversation-Id": "shared"}

        client.post(
            "/v1/chat/completions",
            json={"model": "intake", "messages": [{"role": "user", "content": "first"}]},
            headers=headers,
        )
        client.post(
            "/v1/chat/completions",
            json={"model": "writer", "messages": [{"role": "user", "content": "second"}]},
            headers=headers,
        )

        # The writer starts fresh: no server-side history was handed to it.
        assert mock_exec.call_args.kwargs["message_history"] is None

    @patch("initrunner.server.app.execute_run_sync")
    def test_history_is_kept_per_agent(self, mock_exec):
        mock_exec.return_value = _ok()
        client = _client()
        headers = {"X-Conversation-Id": "shared"}

        for _ in range(2):
            client.post(
                "/v1/chat/completions",
                json={"model": "intake", "messages": [{"role": "user", "content": "hi"}]},
                headers=headers,
            )

        assert mock_exec.call_args.kwargs["message_history"] is not None


class TestApprovalRouting:
    def test_resume_finds_the_owning_agent(self):
        """Pending rows record the agent, so a resume needs no extra parameter."""
        from initrunner.server.app import _member_for_run

        members = {
            key: ServedMember(key=key, role=_role(key), agent=MagicMock())
            for key in ("intake", "writer")
        }
        audit = MagicMock()
        audit.load_pending_approvals.return_value = [MagicMock(agent_name="writer-agent")]

        member = _member_for_run("run-1", audit, members, None)

        assert member is not None
        assert member.key == "writer"

    def test_unknown_run_has_no_owner(self):
        from initrunner.server.app import _member_for_run

        audit = MagicMock()
        audit.load_pending_approvals.return_value = []

        assert _member_for_run("run-1", audit, {"a": MagicMock()}, None) is None

    def test_resume_returns_404_for_unknown_run(self):
        audit = MagicMock()
        audit.load_pending_approvals.return_value = []
        client = _client(audit_logger=audit)

        resp = client.post("/v1/approvals/nope", json={"call-1": True})

        assert resp.status_code == 404


class TestGroupSecurity:
    def test_group_auth_applies_to_every_agent(self):
        client = _client(api_key="secret")

        assert client.get("/v1/models").status_code == 401
        assert (
            client.get("/v1/models", headers={"Authorization": "Bearer secret"}).status_code == 200
        )

    def test_health_stays_open(self):
        client = _client(api_key="secret")

        assert client.get("/health").status_code == 200
