"""Tests for /api/runs routes."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from initrunner.dashboard.deps import _role_id


def test_execute_run(client, mock_roles):
    agent_id = _role_id(Path("/tmp/roles/agent-a.yaml"))

    mock_result = MagicMock()
    mock_result.run_id = "run-123"
    mock_result.output = "Hello!"
    mock_result.tokens_in = 10
    mock_result.tokens_out = 5
    mock_result.total_tokens = 15
    mock_result.tool_calls = 0
    mock_result.tool_call_names = []
    mock_result.duration_ms = 100
    mock_result.success = True
    mock_result.error = None

    with (
        patch("initrunner.services.execution.build_agent_sync") as mock_build,
        patch("initrunner.services.execution.execute_run_sync") as mock_exec,
    ):
        mock_role = MagicMock()
        mock_role.spec.memory = None
        mock_build.return_value = (mock_role, MagicMock())
        mock_exec.return_value = (mock_result, [])

        resp = client.post(
            "/api/runs",
            json={"agent_id": agent_id, "prompt": "Hello"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["run_id"] == "run-123"
    assert data["output"] == "Hello!"
    assert data["success"] is True
    assert data["message_history"] == "[]"


def test_execute_run_not_found(client):
    resp = client.post(
        "/api/runs",
        json={"agent_id": "000000000000", "prompt": "Hello"},
    )
    assert resp.status_code == 404


def test_stream_run_not_found(client):
    resp = client.post(
        "/api/runs/stream",
        json={"agent_id": "000000000000", "prompt": "Hello"},
    )
    assert resp.status_code == 404
