"""Spawn tool: non-blocking parallel agent execution via asyncio."""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from concurrent.futures import Future
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic_ai.toolsets.function import FunctionToolset

from initrunner.agent.reasoning import SpawnedTask
from initrunner.agent.schema.tools import SpawnToolConfig
from initrunner.agent.tools._registry import ToolBuildContext, register_tool

if TYPE_CHECKING:
    from initrunner.agent.delegation import AgentInvoker

logger = logging.getLogger(__name__)


class SpawnPool:
    """Manages background agent tasks on a private asyncio event loop."""

    def __init__(self, max_concurrent: int, timeout: int) -> None:
        self._max_concurrent = max_concurrent
        self._timeout = timeout
        self._tasks: dict[str, SpawnedTask] = {}
        self._futures: dict[str, Future[str]] = {}
        self._semaphore: asyncio.Semaphore | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._start_loop()

    def _start_loop(self) -> None:
        self._loop = asyncio.new_event_loop()
        self._semaphore = asyncio.Semaphore(self._max_concurrent)
        self._thread = threading.Thread(
            target=self._loop.run_forever, daemon=True, name="spawn-pool"
        )
        self._thread.start()

    def submit(
        self,
        task_id: str,
        agent_name: str,
        prompt: str,
        invoker: AgentInvoker,
    ) -> SpawnedTask:
        """Submit a task. Returns immediately."""
        assert self._loop is not None
        assert self._semaphore is not None
        task = SpawnedTask(
            task_id=task_id,
            agent_name=agent_name,
            prompt=prompt,
            started_at=time.monotonic(),
        )
        self._tasks[task_id] = task

        semaphore = self._semaphore
        assert semaphore is not None

        async def _run() -> str:
            async with semaphore:
                return await asyncio.to_thread(invoker.invoke, prompt)

        future = asyncio.run_coroutine_threadsafe(
            asyncio.wait_for(_run(), timeout=self._timeout), self._loop
        )
        # Wrap in a callback to update task state
        future.add_done_callback(lambda f: self._on_done(task_id, f))
        self._futures[task_id] = future
        return task

    def _on_done(self, task_id: str, future: Future[str]) -> None:
        task = self._tasks.get(task_id)
        if task is None:
            return
        try:
            result = future.result()
            task.status = "completed"
            task.result = result
        except TimeoutError:
            task.status = "timeout"
            task.error = f"Timed out after {self._timeout}s"
        except asyncio.CancelledError:
            task.status = "failed"
            task.error = "Cancelled"
        except Exception as e:
            task.status = "failed"
            task.error = str(e)

    def poll(self, task_ids: list[str] | None = None) -> list[SpawnedTask]:
        """Return status of requested tasks (or all)."""
        if task_ids is None:
            return list(self._tasks.values())
        return [self._tasks[tid] for tid in task_ids if tid in self._tasks]

    def await_tasks(self, task_ids: list[str], timeout: float | None = None) -> list[SpawnedTask]:
        """Block until all specified tasks complete."""
        futures = [self._futures[tid] for tid in task_ids if tid in self._futures]
        for f in futures:
            try:
                f.result(timeout=timeout)
            except Exception:
                pass  # Status already updated by _on_done
        return [self._tasks[tid] for tid in task_ids if tid in self._tasks]

    def await_any(self, task_ids: list[str], timeout: float | None = None) -> SpawnedTask | None:
        """Block until any one task completes."""
        while True:
            for tid in task_ids:
                task = self._tasks.get(tid)
                if task and task.status != "running":
                    return task
            # Brief sleep to avoid busy-wait
            time.sleep(0.05)

    def cancel(self, task_id: str) -> bool:
        """Cancel a running task."""
        future = self._futures.get(task_id)
        if future is None:
            return False
        future.cancel()
        task = self._tasks.get(task_id)
        if task and task.status == "running":
            task.status = "failed"
            task.error = "Cancelled"
        return True

    def shutdown(self) -> None:
        """Stop the event loop and clean up."""
        if self._loop is None:
            return
        for future in self._futures.values():
            future.cancel()
        self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread is not None:
            self._thread.join(timeout=5)
        self._loop.close()
        self._loop = None


def _format_tasks(tasks: list[SpawnedTask]) -> str:
    if not tasks:
        return "No spawned tasks."
    lines = ["Spawned Tasks:"]
    for t in tasks:
        elapsed = time.monotonic() - t.started_at
        status_detail = ""
        if t.status == "completed":
            result_preview = (t.result or "")[:200]
            status_detail = f" -> {result_preview}"
        elif t.status == "failed":
            status_detail = f" -> ERROR: {t.error}"
        elif t.status == "timeout":
            status_detail = f" -> TIMEOUT: {t.error}"
        lines.append(f"  {t.task_id} [{t.agent_name}] {t.status} ({elapsed:.1f}s){status_detail}")
    return "\n".join(lines)


def _build_invokers(
    config: SpawnToolConfig,
    ctx: ToolBuildContext,
) -> dict[str, AgentInvoker]:
    """Build an invoker for each agent ref."""
    from initrunner.agent.delegation import InlineInvoker, McpInvoker

    invokers: dict[str, AgentInvoker] = {}
    role_dir = ctx.role_dir or Path(".")

    for agent_ref in config.agents:
        if agent_ref.role_file:
            role_path = (role_dir / agent_ref.role_file).resolve()
            shared_path = None
            shared_max = 1000
            if config.shared_memory:
                shared_path = config.shared_memory.store_path
                shared_max = config.shared_memory.max_memories
            invokers[agent_ref.name] = InlineInvoker(
                role_path=role_path,
                max_depth=config.max_depth,
                timeout=config.timeout_seconds,
                shared_memory_path=shared_path,
                shared_max_memories=shared_max,
                source_metadata=ctx.role.metadata,
            )
        elif agent_ref.url:
            invokers[agent_ref.name] = McpInvoker(
                base_url=agent_ref.url,
                agent_name=agent_ref.name,
                timeout=config.timeout_seconds,
                source_metadata=ctx.role.metadata,
            )
    return invokers


@register_tool("spawn", SpawnToolConfig, run_scoped=True)
def build_spawn_toolset(
    config: SpawnToolConfig,
    ctx: ToolBuildContext,
) -> FunctionToolset:
    """Build the spawn toolset for non-blocking parallel agent execution."""
    from initrunner._ids import generate_id

    invokers = _build_invokers(config, ctx)
    pool = SpawnPool(
        max_concurrent=config.max_concurrent,
        timeout=config.timeout_seconds,
    )
    agent_descriptions = {a.name: a.description for a in config.agents}
    toolset = FunctionToolset()

    @toolset.tool_plain
    def spawn_agent(agent_name: str, prompt: str) -> str:
        """Spawn a background agent to work on a task. Returns immediately.

        Args:
            agent_name: Name of the agent to spawn.
            prompt: The task description for the agent.
        """
        if agent_name not in invokers:
            available = ", ".join(invokers.keys())
            return f"Unknown agent '{agent_name}'. Available: {available}"
        task_id = generate_id(8)
        pool.submit(task_id, agent_name, prompt, invokers[agent_name])
        desc = agent_descriptions.get(agent_name, "")
        return f"Spawned {agent_name} as {task_id}{': ' + desc if desc else ''}"

    @toolset.tool_plain
    def poll_tasks(task_ids: list[str] | None = None) -> str:
        """Check status of spawned tasks.

        Args:
            task_ids: Specific task IDs to check, or None for all.
        """
        return _format_tasks(pool.poll(task_ids))

    @toolset.tool_plain
    def await_tasks(task_ids: list[str]) -> str:
        """Block until all specified tasks complete and return their results.

        Args:
            task_ids: Task IDs to wait for.
        """
        tasks = pool.await_tasks(task_ids)
        return _format_tasks(tasks)

    @toolset.tool_plain
    def await_any(task_ids: list[str]) -> str:
        """Block until any one of the specified tasks completes.

        Args:
            task_ids: Task IDs to wait on.
        """
        task = pool.await_any(task_ids)
        if task is None:
            return "No tasks found."
        return _format_tasks([task])

    @toolset.tool_plain
    def cancel_task(task_id: str) -> str:
        """Cancel a running background task.

        Args:
            task_id: The ID of the task to cancel.
        """
        if pool.cancel(task_id):
            return f"Cancelled {task_id}."
        return f"Task '{task_id}' not found or already finished."

    return toolset
