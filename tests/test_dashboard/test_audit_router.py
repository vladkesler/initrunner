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
        "thinking_tokens": 7,
        "reasoning_tokens": 3,
        "tool_calls": 0,
        "duration_ms": 200,
        "success": True,
        "error": None,
        "trigger_type": None,
        "event_timeline_json": None,
        "judge_verdicts": None,
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


def test_query_audit_includes_thinking_tokens(client):
    records = [_make_audit_record(thinking_tokens=42, reasoning_tokens=9)]
    with patch(
        "initrunner.services.operations.query_audit_sync",
        return_value=records,
    ):
        resp = client.get("/api/audit")

    assert resp.status_code == 200
    data = resp.json()
    assert data[0]["thinking_tokens"] == 42
    assert data[0]["reasoning_tokens"] == 9


def test_get_audit_run_detail(client):
    record = _make_audit_record(
        event_timeline_json='[{"event": "tool_call", "name": "search"}]',
        judge_verdicts='[{"passed": true, "score": 0.9}]',
    )
    with patch(
        "initrunner.services.operations.query_audit_sync",
        return_value=[record],
    ):
        resp = client.get("/api/audit/run-1")

    assert resp.status_code == 200
    data = resp.json()
    assert data["run_id"] == "run-1"
    assert data["thinking_tokens"] == 7
    assert data["event_timeline"] == [{"event": "tool_call", "name": "search"}]
    assert data["judge_verdicts"] == [{"passed": True, "score": 0.9}]


def test_audit_run_detail_404_on_missing_run(client):
    with patch(
        "initrunner.services.operations.query_audit_sync",
        return_value=[],
    ):
        resp = client.get("/api/audit/does-not-exist")

    assert resp.status_code == 404


def test_audit_run_detail_malformed_json_returns_null(client):
    record = _make_audit_record(event_timeline_json="{bad", judge_verdicts="not json")
    with patch(
        "initrunner.services.operations.query_audit_sync",
        return_value=[record],
    ):
        resp = client.get("/api/audit/run-1")

    assert resp.status_code == 200
    data = resp.json()
    assert data["event_timeline"] is None
    assert data["judge_verdicts"] is None
