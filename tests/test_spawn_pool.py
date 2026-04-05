"""Tests for SpawnPool.await_any timeout and edge-case handling."""

from __future__ import annotations

import time
from unittest.mock import MagicMock

from initrunner.agent.tools.spawn import SpawnPool


class TestAwaitAny:
    def test_returns_completed_task(self):
        pool = SpawnPool(max_concurrent=2, timeout=10)
        invoker = MagicMock()
        invoker.invoke.return_value = "done"

        pool.submit("t1", "agent-a", "hello", invoker)
        task = pool.await_any(["t1"], timeout=5)

        assert task is not None
        assert task.task_id == "t1"
        assert task.status == "completed"
        assert task.result == "done"
        pool.shutdown()

    def test_timeout_returns_none(self):
        pool = SpawnPool(max_concurrent=2, timeout=30)
        invoker = MagicMock()
        invoker.invoke.side_effect = lambda p: time.sleep(10)

        pool.submit("t1", "agent-a", "hello", invoker)
        start = time.monotonic()
        task = pool.await_any(["t1"], timeout=0.15)
        elapsed = time.monotonic() - start

        assert task is None
        assert elapsed < 1.0  # Should return quickly after timeout
        pool.shutdown()

    def test_unknown_ids_returns_none(self):
        pool = SpawnPool(max_concurrent=2, timeout=10)
        start = time.monotonic()
        task = pool.await_any(["bogus-id"], timeout=None)
        elapsed = time.monotonic() - start

        assert task is None
        assert elapsed < 0.5  # Should return immediately
        pool.shutdown()
