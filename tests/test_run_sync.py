"""Regression tests for initrunner._async.run_sync()."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import anyio
import pytest

from initrunner._async import run_sync


async def _double(n: int) -> int:
    return n * 2


def test_run_sync_no_loop():
    """run_sync() works from plain synchronous context (no event loop running)."""
    assert run_sync(_double(21)) == 42


@pytest.mark.anyio
async def test_run_sync_inside_running_loop():
    """run_sync() offloads to a worker thread when called inside a running loop."""
    result = await anyio.to_thread.run_sync(lambda: run_sync(_double(7)))
    assert result == 14


@pytest.mark.anyio
async def test_sync_wrapper_from_async_context():
    """A real sync wrapper (run_flow_graph_sync) works when called from async context."""
    sentinel = ({"ref": "mock"}, "entry", 100, False)

    with patch(
        "initrunner.flow.graph.run_flow_graph_async",
        new_callable=AsyncMock,
        return_value=sentinel,
    ):
        from initrunner.flow.graph import run_flow_graph_sync

        result = await anyio.to_thread.run_sync(
            lambda: run_flow_graph_sync(None, {}, "test")  # type: ignore[arg-type]
        )
        assert result == sentinel
