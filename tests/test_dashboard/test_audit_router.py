"""Tests for /api/audit routes."""

from unittest.mock import MagicMock, patch


def _make_audit_record(**overrides):
    r = MagicMock()
    defaults = {
        "run_id": "run-1",
        "agent_name": "test-agent",
        "timestamp": "2026-03-23T10:00:00",
        "user_prompt": "hello",
        "model": "gpt-4o",
        "provider": "openai",
        "output": "Hi there!",
        "tokens_in": 10,
        "tokens_out": 5,
        "total_tokens": 15,
        "tool_calls": 0,
        "duration_ms": 200,
        "success": True,
        "error": None,
        "trigger_type": None,
    }
    defaults.update(overrides)
    for k, v in defaults.items():
        setattr(r, k, v)
    return r


def test_query_audit(client):
    records = [_make_audit_record(), _make_audit_record(run_id="run-2")]

    with patch(
        "initrunner.services.operations.query_audit_sync",
        return_value=records,
    ):
        resp = client.get("/api/audit")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    assert data[0]["run_id"] == "run-1"


def test_query_audit_with_filter(client):
    with patch(
        "initrunner.services.operations.query_audit_sync",
        return_value=[],
    ) as mock_q:
        resp = client.get("/api/audit?agent_name=my-agent&limit=10")

    assert resp.status_code == 200
    mock_q.assert_called_once()
    call_kwargs = mock_q.call_args[1]
    assert call_kwargs["agent_name"] == "my-agent"
    assert call_kwargs["limit"] == 10


def test_query_audit_empty(client):
    with patch(
        "initrunner.services.operations.query_audit_sync",
        return_value=[],
    ):
        resp = client.get("/api/audit")

    assert resp.status_code == 200
    assert resp.json() == []
