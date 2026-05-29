"""Regression tests: the event timeline is captured and persisted for any
audited run, not only when a live ``on_event`` consumer is attached.

Covers ITEM 3: ``initrunner run`` (buffered ``execute_run`` and ``-f stream``
``execute_run_stream``) must write a non-null ``event_timeline_json`` to the
audit DB, while ``--no-audit`` / no-tool runs stay sane.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from pydantic_ai import Agent
from pydantic_ai.models.test import TestModel

from initrunner.agent.executor import execute_run, execute_run_stream
from initrunner.agent.executor_output import build_timeline_from_messages
from initrunner.agent.schema.role import RoleDefinition
from initrunner.audit.logger import AuditLogger


def _role() -> RoleDefinition:
    return RoleDefinition.model_validate(
        {
            "apiVersion": "initrunner/v1",
            "kind": "Agent",
            "metadata": {"name": "timeline-agent", "description": "d"},
            "spec": {
                "role": "You are a test.",
                "model": {"provider": "openai", "name": "gpt-4o-mini"},
                "output": {"type": "text"},
            },
        }
    )


def _add(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b


def _tool_agent() -> Agent:
    return Agent(TestModel(), tools=[_add])


def _persisted_timeline(db_path: Path) -> str | None:
    conn = sqlite3.connect(str(db_path))
    try:
        row = conn.execute(
            "SELECT event_timeline_json FROM audit_log ORDER BY id DESC LIMIT 1"
        ).fetchone()
    finally:
        conn.close()
    return row[0] if row else None


def _types(timeline: list[dict]) -> set[str]:
    return {entry["type"] for entry in timeline}


# ---------------------------------------------------------------------------
# Buffered path (execute_run / `initrunner run`)
# ---------------------------------------------------------------------------


def test_buffered_run_persists_tool_timeline(tmp_path):
    """A buffered, audited, tool-using run writes a non-empty timeline with
    function_tool_call and function_tool_result entries."""
    db_path = tmp_path / "audit.db"
    with AuditLogger(db_path) as logger:
        result, _ = execute_run(_tool_agent(), _role(), "add 2 and 3", audit_logger=logger)

    assert "_add" in result.tool_call_names
    types = _types(result.event_timeline)
    assert "function_tool_call" in types
    assert "function_tool_result" in types

    raw = _persisted_timeline(db_path)
    assert raw is not None
    persisted = json.loads(raw)
    assert any(e["type"] == "function_tool_call" and e["tool_name"] == "_add" for e in persisted)
    assert any(e["type"] == "function_tool_result" for e in persisted)


def test_buffered_run_no_audit_skips_timeline():
    """--no-audit (audit_logger=None) records no timeline -- zero overhead."""
    result, _ = execute_run(_tool_agent(), _role(), "add 2 and 3", audit_logger=None)
    assert result.event_timeline == []


def test_buffered_no_tool_run_has_empty_timeline(tmp_path):
    """An audited run with no tools produces a sane (no tool-call) timeline."""
    db_path = tmp_path / "audit.db"
    agent = Agent(TestModel(call_tools=[]))
    with AuditLogger(db_path) as logger:
        result, _ = execute_run(agent, _role(), "say hi", audit_logger=logger)

    assert "function_tool_call" not in _types(result.event_timeline)
    raw = _persisted_timeline(db_path)
    if raw is not None:
        assert "function_tool_call" not in {e["type"] for e in json.loads(raw)}


# ---------------------------------------------------------------------------
# Streaming path (execute_run_stream / `initrunner run -f stream`)
# ---------------------------------------------------------------------------


def test_stream_run_without_on_event_persists_timeline(tmp_path):
    """The streaming path with no external on_event consumer (the CLI -f stream
    case) still captures and persists a tool-call/result timeline."""
    db_path = tmp_path / "audit.db"
    with AuditLogger(db_path) as logger:
        result, _ = execute_run_stream(_tool_agent(), _role(), "add 2 and 3", audit_logger=logger)

    types = _types(result.event_timeline)
    assert "function_tool_call" in types
    assert "function_tool_result" in types

    raw = _persisted_timeline(db_path)
    assert raw is not None
    assert any(e["type"] == "function_tool_call" for e in json.loads(raw))


def test_stream_run_no_audit_skips_timeline():
    """Streaming with no audit logger records no timeline."""
    result, _ = execute_run_stream(_tool_agent(), _role(), "add 2 and 3", audit_logger=None)
    assert result.event_timeline == []


# ---------------------------------------------------------------------------
# Programmatic on_event path must not regress
# ---------------------------------------------------------------------------


def test_on_event_path_still_captures_timeline(tmp_path):
    """The pre-existing live on_event backbone keeps building and persisting
    the timeline; this fix must not regress it."""
    from initrunner._async import run_sync
    from initrunner.agent.executor import execute_run_stream_async

    db_path = tmp_path / "audit.db"
    seen: list = []
    with AuditLogger(db_path) as logger:
        result, _ = run_sync(
            execute_run_stream_async(
                _tool_agent(),
                _role(),
                "add 2 and 3",
                audit_logger=logger,
                on_event=seen.append,
            )
        )

    assert seen, "on_event consumer received events"
    assert "function_tool_call" in _types(result.event_timeline)
    raw = _persisted_timeline(db_path)
    assert raw is not None
    assert any(e["type"] == "function_tool_call" for e in json.loads(raw))


# ---------------------------------------------------------------------------
# The message-derived builder shape matches the live-event shape
# ---------------------------------------------------------------------------


def test_build_timeline_from_messages_shapes():
    """build_timeline_from_messages emits the same entry shapes as the live
    build_timeline_entry path (no parallel format)."""
    agent = _tool_agent()
    res = agent.run_sync("add 4 and 5")
    timeline = build_timeline_from_messages(res.all_messages())

    calls = [e for e in timeline if e["type"] == "function_tool_call"]
    results = [e for e in timeline if e["type"] == "function_tool_result"]
    assert calls and results

    call = calls[0]
    assert set(call) == {
        "type",
        "timestamp_unix_ms",
        "tool_call_id",
        "tool_name",
        "args_preview",
        "args_valid",
    }
    result_entry = results[0]
    assert set(result_entry) == {
        "type",
        "timestamp_unix_ms",
        "content_preview",
        "part_type",
    }


def test_build_timeline_from_messages_never_raises_on_garbage():
    """A malformed message yields no entry rather than crashing."""
    assert build_timeline_from_messages([object(), None]) == []


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
