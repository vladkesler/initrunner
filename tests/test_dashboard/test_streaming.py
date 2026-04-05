"""Regression tests for dashboard SSE streaming -- sentinel/future race.

The five ``stream_*_sse`` helpers in ``initrunner/dashboard/streaming.py``
push a ``None`` sentinel from a ``finally`` block *before* the executor
future is marked done.  If the consumer reads the sentinel and then calls
``.result()`` synchronously, it hits ``InvalidStateError``.  The fix is to
``await`` the future instead.  These tests force the race deterministically
and assert each helper emits a ``result`` event, not an ``error`` event.
"""

from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def _mock_run_result():
    """Minimal RunResult mock."""
    r = MagicMock()
    r.run_id = "run-1"
    r.output = "ok"
    r.tokens_in = 1
    r.tokens_out = 1
    r.total_tokens = 2
    r.tool_calls = 0
    r.tool_call_names = []
    r.duration_ms = 10
    r.success = True
    r.error = None
    return r


@pytest.fixture
def _mock_role():
    role = MagicMock()
    role.spec.output.type = "text"
    role.spec.memory = None
    role.spec.session = None
    return role


# ── helpers ──────────────────────────────────────────────────────────────


async def _collect(aiter):
    """Drain an async iterator into a list."""
    return [item async for item in aiter]


def _parse_last_data_event(events: list[str]) -> dict:
    """Parse the last ``data:`` SSE line into a dict."""
    for event in reversed(events):
        if event.startswith("data: "):
            return json.loads(event.removeprefix("data: ").strip())
    raise AssertionError("No data event found")


# ── stream_run_sse ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_stream_run_sse_awaits_future(_mock_run_result, _mock_role):
    """stream_run_sse must await the executor future, not call .result()."""
    from initrunner.dashboard.streaming import stream_run_sse

    gate = threading.Event()

    def slow_build(path, **kw):
        return (_mock_role, MagicMock())

    def slow_stream(agent, role, prompt, **kw):
        # Simulate sentinel arriving before executor marks future done:
        # the finally block fires immediately, but we stall the return.
        gate.wait(timeout=5)
        return (_mock_run_result, [])

    with (
        patch("initrunner.services.execution.build_agent_sync", side_effect=slow_build),
        patch("initrunner.services.execution.execute_run_stream_sync", side_effect=slow_stream),
    ):

        async def run():
            events = []
            async for event in stream_run_sse(Path("/tmp/role.yaml"), "hello"):
                events.append(event)
            return events

        # Release the gate after a brief delay so the executor future resolves
        async def release():
            await asyncio.sleep(0.05)
            gate.set()

        results, _ = await asyncio.gather(run(), release())

    last = _parse_last_data_event(results)
    assert last["type"] == "result", f"Expected result event, got: {last}"
    assert last["data"]["success"] is True


@pytest.mark.asyncio
async def test_stream_run_sse_structured_output_fallback(_mock_run_result, _mock_role):
    """Structured output roles use non-streaming execution, no token events."""
    from initrunner.dashboard.streaming import stream_run_sse

    _mock_role.spec.output.type = "json_schema"

    def fake_build(path, **kw):
        return (_mock_role, MagicMock())

    def fake_run_sync(agent, role, prompt, **kw):
        return (_mock_run_result, [])

    with (
        patch("initrunner.services.execution.build_agent_sync", side_effect=fake_build),
        patch("initrunner.services.execution.execute_run_sync", side_effect=fake_run_sync),
        patch(
            "initrunner.services.execution.execute_run_stream_sync",
            side_effect=AssertionError("streaming should not be called"),
        ),
    ):
        events = await _collect(stream_run_sse(Path("/tmp/role.yaml"), "hello"))

    # No token events emitted
    token_events = [e for e in events if '"type": "token"' in e]
    assert token_events == []

    last = _parse_last_data_event(events)
    assert last["type"] == "result"
    assert last["data"]["success"] is True


# ── stream_flow_run_sse ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_stream_flow_run_sse_awaits_future():
    """stream_flow_run_sse must await the executor future."""
    from initrunner.dashboard.streaming import stream_flow_run_sse

    gate = threading.Event()

    flow_result = MagicMock()
    flow_result.output = "done"
    flow_result.output_mode = "last"
    flow_result.final_agent_name = "agent-1"
    flow_result.steps = []
    flow_result.total_tokens_in = 1
    flow_result.total_tokens_out = 1
    flow_result.total_duration_ms = 10
    flow_result.success = True
    flow_result.error = None
    flow_result.entry_messages = None

    async def slow_flow(*a, **kw):
        await asyncio.sleep(0.05)
        gate.set()
        return flow_result

    with patch(
        "initrunner.services.flow.run_flow_once_async",
        side_effect=slow_flow,
    ):
        flow_def = MagicMock()

        async def run():
            return [e async for e in stream_flow_run_sse(flow_def, Path("/tmp"), "hello")]

        async def release():
            await asyncio.sleep(0.05)
            gate.set()

        results, _ = await asyncio.gather(run(), release())

    last = _parse_last_data_event(results)
    assert last["type"] == "result", f"Expected result event, got: {last}"
    assert last["data"]["success"] is True


# ── stream_team_run_sse ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_stream_team_run_sse_awaits_future():
    """stream_team_run_sse must await the executor future."""
    from initrunner.dashboard.streaming import stream_team_run_sse

    gate = threading.Event()

    team_result = MagicMock()
    team_result.team_run_id = "t-1"
    team_result.final_output = "done"
    team_result.agent_names = []
    team_result.agent_results = []
    team_result.total_tokens_in = 1
    team_result.total_tokens_out = 1
    team_result.total_tokens = 2
    team_result.total_duration_ms = 10
    team_result.success = True
    team_result.error = None

    async def slow_team(*a, **kw):
        await asyncio.sleep(0.05)
        gate.set()
        return team_result

    with patch(
        "initrunner.team.graph.run_team_graph_async",
        side_effect=slow_team,
    ):
        team_def = MagicMock()

        async def run():
            return [e async for e in stream_team_run_sse(team_def, Path("/tmp"), "hello")]

        async def release():
            await asyncio.sleep(0.05)
            gate.set()

        results, _ = await asyncio.gather(run(), release())

    last = _parse_last_data_event(results)
    assert last["type"] == "result", f"Expected result event, got: {last}"
    assert last["data"]["success"] is True


# ── stream_ingest_sse ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_stream_ingest_sse_awaits_future():
    """stream_ingest_sse must await the executor future."""
    from initrunner.dashboard.streaming import stream_ingest_sse

    gate = threading.Event()

    ingest_stats = MagicMock()
    ingest_stats.new = 1
    ingest_stats.updated = 0
    ingest_stats.skipped = 0
    ingest_stats.errored = 0
    ingest_stats.total_chunks = 5
    ingest_stats.file_results = []

    mock_role = MagicMock()

    def slow_ingest(role, path, **kw):
        gate.wait(timeout=5)
        return ingest_stats

    with (
        patch("initrunner.agent.loader.load_role", return_value=mock_role),
        patch("initrunner.agent.loader.resolve_role_model", return_value=mock_role),
        patch(
            "initrunner.services.operations.run_ingest_sync",
            side_effect=slow_ingest,
        ),
    ):

        async def run():
            return [e async for e in stream_ingest_sse(Path("/tmp/role.yaml"))]

        async def release():
            await asyncio.sleep(0.05)
            gate.set()

        results, _ = await asyncio.gather(run(), release())

    last = _parse_last_data_event(results)
    assert last["type"] == "result", f"Expected result event, got: {last}"
    assert last["data"]["new"] == 1


# ── stream_team_ingest_sse ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_stream_team_ingest_sse_awaits_future():
    """stream_team_ingest_sse must await the executor future."""
    from initrunner.dashboard.streaming import stream_team_ingest_sse

    gate = threading.Event()

    ingest_stats = MagicMock()
    ingest_stats.new = 2
    ingest_stats.updated = 1
    ingest_stats.skipped = 0
    ingest_stats.errored = 0
    ingest_stats.total_chunks = 8
    ingest_stats.file_results = []

    def slow_ingest(*a, **kw):
        gate.wait(timeout=5)
        return ingest_stats

    from initrunner.agent.schema.ingestion import ChunkingConfig, EmbeddingConfig

    team_def = MagicMock()
    team_def.metadata.name = "test-team"
    team_def.spec.shared_documents.store_path = None
    team_def.spec.shared_documents.store_backend = "lancedb"
    team_def.spec.shared_documents.sources = []
    team_def.spec.shared_documents.embeddings = EmbeddingConfig()
    team_def.spec.shared_documents.chunking = ChunkingConfig()
    team_def.spec.model = None

    with patch(
        "initrunner.ingestion.pipeline.run_ingest",
        side_effect=slow_ingest,
    ):

        async def run():
            return [e async for e in stream_team_ingest_sse(team_def, Path("/tmp"))]

        async def release():
            await asyncio.sleep(0.05)
            gate.set()

        results, _ = await asyncio.gather(run(), release())

    last = _parse_last_data_event(results)
    assert last["type"] == "result", f"Expected result event, got: {last}"
    assert last["data"]["new"] == 2


# ── _sse_pump ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sse_pump_yields_events_and_result():
    """_sse_pump yields queued events then a result event."""
    from initrunner.dashboard.streaming import _sse_pump

    queue: asyncio.Queue[str | None] = asyncio.Queue()

    async def _work():
        queue.put_nowait('data: {"type": "token", "data": "hi"}\n\n')
        queue.put_nowait(None)
        return {"answer": 42}

    task = asyncio.create_task(_work())
    await asyncio.sleep(0)  # let task run

    events = [e async for e in _sse_pump(queue, task, lambda r: r, "test error")]

    assert events[0] == 'data: {"type": "token", "data": "hi"}\n\n'
    last = json.loads(events[-1].removeprefix("data: ").strip())
    assert last["type"] == "result"
    assert last["data"]["answer"] == 42


@pytest.mark.asyncio
async def test_sse_pump_yields_error_on_exception():
    """_sse_pump yields an error event when the work future raises."""
    from initrunner.dashboard.streaming import _sse_pump

    queue: asyncio.Queue[str | None] = asyncio.Queue()

    async def _work():
        queue.put_nowait(None)
        raise RuntimeError("boom")

    task = asyncio.create_task(_work())
    await asyncio.sleep(0)

    events = [e async for e in _sse_pump(queue, task, lambda r: r, "test error")]

    last = json.loads(events[-1].removeprefix("data: ").strip())
    assert last["type"] == "error"
    assert "boom" in last["data"]


@pytest.mark.asyncio
async def test_sse_pump_yields_error_on_build_result_failure():
    """_sse_pump yields an error event when build_result raises."""
    from initrunner.dashboard.streaming import _sse_pump

    queue: asyncio.Queue[str | None] = asyncio.Queue()

    async def _work():
        queue.put_nowait(None)
        return "ok"

    task = asyncio.create_task(_work())
    await asyncio.sleep(0)

    def bad_build(_raw: object) -> dict:
        raise ValueError("build failed")

    events = [e async for e in _sse_pump(queue, task, bad_build, "test error")]

    last = json.loads(events[-1].removeprefix("data: ").strip())
    assert last["type"] == "error"
    assert "build failed" in last["data"]
