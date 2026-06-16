"""Tests for SpawnPool.await_any timeout and edge-case handling."""

from __future__ import annotations

import time
from unittest.mock import MagicMock

from initrunner.agent.delegation import (
    enter_delegation,
    get_current_chain,
    get_current_depth,
    reset_context,
)
from initrunner.agent.tools.spawn import SpawnPool


class TestSpawnInheritsDelegationDepth:
    def test_spawned_worker_inherits_parent_depth(self):
        """Regression: a spawned sub-agent must start from the parent's delegation
        depth, not from 0. The pool runs the invoker on a private loop + worker
        thread, so without explicit re-seeding the max_depth limit never
        accumulates and a recursive spawn topology fans out unbounded."""
        reset_context()
        observed: dict[str, object] = {}

        class _RecordingInvoker:
            def invoke(self, prompt: str) -> str:
                # Runs on the spawn worker thread.
                observed["depth"] = get_current_depth()
                observed["chain"] = get_current_chain()
                return "ok"

        pool = SpawnPool(max_concurrent=2, timeout=10)
        try:
            enter_delegation("parent", max_depth=5)  # parent run now at depth 1
            assert get_current_depth() == 1
            pool.submit("t1", "child", "hi", _RecordingInvoker())
            tasks = pool.await_tasks(["t1"], timeout=5)
            assert tasks[0].status == "completed"
            # Before the fix the worker thread observed depth 0 (fresh thread-local).
            assert observed["depth"] == 1
            assert observed["chain"] == ["parent"]
        finally:
            reset_context()
            pool.shutdown()


class TestBulkSubmit:
    def test_bulk_submit_runs_same_prompt_k_times(self):
        pool = SpawnPool(max_concurrent=4, timeout=10)
        invoker = MagicMock()
        invoker.invoke.return_value = "answer"

        task_ids = pool.bulk_submit("ensemble", "agent-a", "same prompt", 3, invoker)
        assert task_ids == ["ensemble_run0", "ensemble_run1", "ensemble_run2"]

        tasks = pool.await_tasks(task_ids)
        assert len(tasks) == 3
        assert all(t.status == "completed" for t in tasks)
        assert all(t.result == "answer" for t in tasks)
        assert invoker.invoke.call_count == 3
        pool.shutdown()

    def test_bulk_submit_returns_ids_immediately(self):
        pool = SpawnPool(max_concurrent=2, timeout=10)
        invoker = MagicMock()
        invoker.invoke.return_value = "x"
        task_ids = pool.bulk_submit("base", "agent-a", "p", 2, invoker)
        assert len(task_ids) == 2
        assert all(tid in {t.task_id for t in pool.poll()} for tid in task_ids)
        pool.await_tasks(task_ids)
        pool.shutdown()


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
