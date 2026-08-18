"""Delegation depth tracking, policy checks, and agent invokers for multi-agent systems."""

from __future__ import annotations

import contextvars
import logging
import os
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Protocol
from uuid import uuid4

if TYPE_CHECKING:
    import httpx

    from initrunner.agent.schema.base import Metadata

logger = logging.getLogger(__name__)

_ERROR_PREFIX = "[DELEGATION ERROR]"


class DelegationDepthExceeded(Exception):
    """Raised when delegation depth exceeds max_depth."""


# ---------------------------------------------------------------------------
# Delegation context (depth + chain)
# ---------------------------------------------------------------------------
#
# Tracked in ContextVars rather than threading.local: asyncio copies the
# current context into each Task and each ``asyncio.to_thread`` call, so every
# delegation branch gets an isolated snapshot that starts from the parent's
# depth. Values are immutable (int / tuple) so a copied context can never
# mutate a sibling branch's state. The SpawnPool runs sub-agents on a private
# event loop via ``run_coroutine_threadsafe`` -- which does NOT carry the
# caller's context -- so it re-seeds the inherited depth explicitly via
# :func:`seed_delegation_context`. (A plain threading.local reset to 0 on every
# spawned worker thread silently defeated the depth limit entirely.)

_depth: contextvars.ContextVar[int] = contextvars.ContextVar("delegation_depth", default=0)
_chain: contextvars.ContextVar[tuple[str, ...]] = contextvars.ContextVar(
    "delegation_chain", default=()
)


def enter_delegation(agent_name: str, max_depth: int) -> None:
    """Increment depth and push agent onto chain. Raises on depth exceeded."""
    depth = _depth.get() + 1
    chain = (*_chain.get(), agent_name)
    _depth.set(depth)
    _chain.set(chain)
    if depth > max_depth:
        chain_str = " -> ".join(chain)
        raise DelegationDepthExceeded(
            f"Delegation depth {depth} exceeds max_depth {max_depth} (chain: {chain_str})"
        )


def exit_delegation() -> None:
    """Decrement depth and pop agent from chain."""
    depth = _depth.get()
    if depth > 0:
        _depth.set(depth - 1)
    chain = _chain.get()
    if chain:
        _chain.set(chain[:-1])


def get_current_depth() -> int:
    return _depth.get()


def get_current_chain() -> list[str]:
    return list(_chain.get())


def seed_delegation_context(depth: int, chain: tuple[str, ...] | list[str]) -> None:
    """Seed the depth/chain inherited from a parent run.

    Used at thread/loop boundaries (e.g. the SpawnPool) where the parent's
    ContextVars are not automatically propagated; the child must start counting
    from the parent's depth instead of from zero, or the depth limit is silently
    defeated by spawning.
    """
    _depth.set(depth)
    _chain.set(tuple(chain))


def reset_context() -> None:
    """Reset delegation context (for testing)."""
    _depth.set(0)
    _chain.set(())


# ---------------------------------------------------------------------------
# Delegation policy check
# ---------------------------------------------------------------------------


def check_delegation_policy(
    source_metadata: Metadata,
    target_name: str,
    target_metadata: Metadata | None = None,
) -> bool:
    """Check whether *source_metadata* agent is allowed to delegate to *target_name*.

    Returns ``True`` (allow) when the policy engine is disabled or
    ``agent_checks`` is False.  When *target_metadata* is available (inline
    delegation), resource attrs include team, tags, and author.  When ``None``
    (MCP remote), the check uses only the target name as resource ID with
    empty attrs.
    """
    from initrunner.agent.executor_auth import _cached_config
    from initrunner.authz import AGENT, DELEGATE, agent_principal_from_role, get_current_engine

    engine = get_current_engine()
    agent_checks = getattr(_cached_config, "agent_checks", False)
    if engine is None or not agent_checks:
        return True

    principal = agent_principal_from_role(source_metadata)

    resource_attrs: dict[str, object] = {}
    if target_metadata is not None:
        resource_attrs = {
            "team": target_metadata.team,
            "author": target_metadata.author,
            "tags": list(target_metadata.tags),
        }

    decision = engine.check(
        principal,
        AGENT,
        DELEGATE,
        resource_id=target_name,
        resource_attrs=resource_attrs,
    )
    return decision.allowed


# ---------------------------------------------------------------------------
# Invoker protocol + implementations
# ---------------------------------------------------------------------------


def _resolve_env_headers(headers_env: dict[str, str]) -> dict[str, str]:
    """Resolve header values from environment variables."""
    headers: dict[str, str] = {}
    for header_name, env_var in headers_env.items():
        value = os.environ.get(env_var, "")
        if value:
            headers[header_name] = value
    return headers


class AgentInvoker(Protocol):
    def invoke(self, prompt: str) -> str: ...


class InlineInvoker:
    """Invoke an agent in-process by loading its role file and running it."""

    def __init__(
        self,
        role_path: Path,
        max_depth: int,
        timeout: int,
        shared_memory_path: str | None = None,
        shared_max_memories: int = 1000,
        source_metadata: Metadata | None = None,
    ) -> None:
        self._role_path = role_path
        self._max_depth = max_depth
        self._timeout = timeout
        self._shared_memory_path = shared_memory_path
        self._shared_max_memories = shared_max_memories
        self._source_metadata = source_metadata

    def invoke(self, prompt: str) -> str:
        from initrunner.agent.executor import execute_run
        from initrunner.agent.loader import load_and_build
        from initrunner.agent.sandbox import _framework_bypass
        from initrunner.runner.run_budget import get_run_budget_tracker

        logger.debug("Delegating to %s (prompt=%r)", self._role_path.name, prompt[:120])

        with _framework_bypass():
            try:
                if self._shared_memory_path:
                    from initrunner.agent.loader import (
                        _load_dotenv,
                        build_agent,
                        load_role,
                        resolve_role_model,
                    )
                    from initrunner.flow.orchestrator import apply_shared_memory

                    _load_dotenv(self._role_path.parent)
                    role = load_role(self._role_path)
                    role = resolve_role_model(role, self._role_path)
                    apply_shared_memory(role, self._shared_memory_path, self._shared_max_memories)
                    # Shared memory is injected by the delegation framework from
                    # trusted coordinator YAML -- relax the store-path restriction
                    # so it doesn't conflict with the sub-agent's default policy.
                    role.spec.security.tools = role.spec.security.tools.model_copy(
                        update={"restrict_db_paths": False}
                    )
                    agent = build_agent(role, role_dir=self._role_path.parent)
                else:
                    role, agent = load_and_build(self._role_path)
            except Exception as e:
                logger.error("Failed to load delegate agent %s: %s", self._role_path, e)
                return f"{_ERROR_PREFIX} Failed to load agent from {self._role_path}: {e}"

            agent_name = role.metadata.name

            # Policy check: is this agent allowed to delegate to the target?
            if self._source_metadata is not None:
                if not check_delegation_policy(self._source_metadata, agent_name, role.metadata):
                    logger.warning(
                        "Delegation denied by policy: %s -> %s",
                        self._source_metadata.name,
                        agent_name,
                    )
                    return (
                        f"{_ERROR_PREFIX} Delegation denied by policy: "
                        f"{self._source_metadata.name} -> {agent_name}"
                    )

            try:
                enter_delegation(agent_name, self._max_depth)
            except DelegationDepthExceeded as e:
                logger.warning("Delegation depth exceeded: %s", e)
                return f"{_ERROR_PREFIX} {e}"

            tracker = get_run_budget_tracker()
            if tracker is not None:
                allowed, reason = tracker.check_before_run()
                if not allowed:
                    exit_delegation()
                    return f"{_ERROR_PREFIX} Run token budget exhausted: {reason}"

            try:
                logger.debug("Executing delegate agent '%s'", agent_name)
                try:
                    result, _ = execute_run(agent, role, prompt)
                except Exception:
                    # Release the 1-token reservation taken by check_before_run
                    # so the parent run is not charged for a sub-agent that
                    # never produced usage.
                    if tracker is not None:
                        tracker.record_usage(0, 0)
                    raise
                if tracker is not None:
                    tracker.record_usage(
                        result.tokens_in, result.tokens_out, cost_usd=result.cost_usd
                    )
                if not result.success:
                    logger.warning("Delegate agent '%s' failed: %s", agent_name, result.error)
                    return f"{_ERROR_PREFIX} Agent '{agent_name}' failed: {result.error}"
                logger.debug(
                    "Delegate agent '%s' succeeded (%d tokens)", agent_name, result.total_tokens
                )
                return result.output
            except Exception as e:
                logger.error("Delegate agent '%s' raised: %s", agent_name, e)
                return f"{_ERROR_PREFIX} Agent '{agent_name}' raised: {e}"
            finally:
                exit_delegation()


class McpInvoker:
    """Invoke a remote agent via HTTP POST to an initrunner serve endpoint."""

    def __init__(
        self,
        base_url: str,
        agent_name: str,
        timeout: int,
        headers_env: dict[str, str] | None = None,
        source_metadata: Metadata | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._agent_name = agent_name
        self._timeout = timeout
        self._headers_env = headers_env or {}
        self._source_metadata = source_metadata

    def _resolve_headers(self) -> dict[str, str]:
        return _resolve_env_headers(self._headers_env)

    def invoke(self, prompt: str) -> str:
        import httpx

        # Policy check: name-only (no target metadata for remote agents)
        if self._source_metadata is not None:
            if not check_delegation_policy(self._source_metadata, self._agent_name):
                logger.warning(
                    "Delegation denied by policy: %s -> %s (remote)",
                    self._source_metadata.name,
                    self._agent_name,
                )
                return (
                    f"{_ERROR_PREFIX} Delegation denied by policy: "
                    f"{self._source_metadata.name} -> {self._agent_name}"
                )

        url = f"{self._base_url}/v1/chat/completions"
        headers = self._resolve_headers()
        headers["Content-Type"] = "application/json"

        payload = {
            "model": self._agent_name,
            "messages": [{"role": "user", "content": prompt}],
        }

        try:
            with httpx.Client(timeout=self._timeout) as client:
                resp = client.post(url, json=payload, headers=headers)
                resp.raise_for_status()
                try:
                    data = resp.json()
                except ValueError:
                    return (
                        f"{_ERROR_PREFIX} Non-JSON response from agent "
                        f"'{self._agent_name}': {resp.text[:200]}"
                    )
                try:
                    content = data["choices"][0]["message"]["content"]
                except (KeyError, IndexError, TypeError):
                    return (
                        f"{_ERROR_PREFIX} Malformed response from agent "
                        f"'{self._agent_name}': {resp.text[:200]}"
                    )
                return content
        except httpx.TimeoutException:
            return (
                f"{_ERROR_PREFIX} Connection timed out to agent '{self._agent_name}' "
                f"at {self._base_url}"
            )
        except httpx.HTTPStatusError as e:
            return (
                f"{_ERROR_PREFIX} HTTP {e.response.status_code} from agent "
                f"'{self._agent_name}': {e.response.text}"
            )
        except Exception as e:
            return f"{_ERROR_PREFIX} Failed to reach agent '{self._agent_name}': {e}"


class A2AInvoker:
    """Invoke a remote agent via A2A 1.0 JSON-RPC.

    Sync facade for ``tool_plain`` delegate tools (PydanticAI runs those on a
    worker thread, so ``anyio.run`` is safe). Failures never raise -- they
    return a ``[DELEGATION ERROR]`` string. Repeated invokes on the same
    instance share a ``context_id`` so the server can keep message history.

    Do not call ``client.close()``: the SDK transport would close the httpx
    client we own.
    """

    def __init__(
        self,
        base_url: str,
        agent_name: str,
        timeout: int,
        headers_env: dict[str, str] | None = None,
        source_metadata: Metadata | None = None,
        _httpx_client_factory: Callable[[], httpx.AsyncClient] | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._agent_name = agent_name
        self._timeout = timeout
        self._headers_env = headers_env or {}
        self._source_metadata = source_metadata
        self._httpx_client_factory = _httpx_client_factory
        self._context_id = str(uuid4())
        self._card = None

    def _resolve_headers(self) -> dict[str, str]:
        return _resolve_env_headers(self._headers_env)

    def invoke(self, prompt: str) -> str:
        # Policy check: name-only (no target metadata for remote agents)
        if self._source_metadata is not None:
            if not check_delegation_policy(self._source_metadata, self._agent_name):
                logger.warning(
                    "Delegation denied by policy: %s -> %s (A2A)",
                    self._source_metadata.name,
                    self._agent_name,
                )
                return (
                    f"{_ERROR_PREFIX} Delegation denied by policy: "
                    f"{self._source_metadata.name} -> {self._agent_name}"
                )

        try:
            from initrunner._compat import require_a2a

            require_a2a()
        except Exception as e:
            return f"{_ERROR_PREFIX} Failed to reach A2A agent '{self._agent_name}': {e}"

        import anyio

        try:
            return anyio.run(self._invoke_async, prompt)
        except Exception as e:
            return f"{_ERROR_PREFIX} Failed to reach A2A agent '{self._agent_name}': {e}"

    async def _invoke_async(self, prompt: str) -> str:
        import httpx
        from a2a.client import ClientConfig, ClientFactory  # type: ignore[import-not-found]
        from a2a.client.card_resolver import A2ACardResolver  # type: ignore[import-not-found]
        from a2a.client.errors import (  # type: ignore[import-not-found]
            A2AClientError,
            A2AClientTimeoutError,
            AgentCardResolutionError,
        )
        from a2a.helpers.proto_helpers import new_text_message  # type: ignore[import-not-found]
        from a2a.types import Role, SendMessageRequest  # type: ignore[import-not-found]
        from a2a.utils.errors import A2AError  # type: ignore[import-not-found]

        headers = self._resolve_headers()
        if self._httpx_client_factory is not None:
            client_cm = self._httpx_client_factory()
        else:
            client_cm = httpx.AsyncClient(headers=headers, timeout=self._timeout)

        try:
            async with client_cm as http:
                for name, value in headers.items():
                    http.headers.setdefault(name, value)
                factory = ClientFactory(ClientConfig(streaming=False, httpx_client=http))
                if self._card is None:
                    self._card = await A2ACardResolver(http, self._base_url).get_agent_card()
                client = factory.create(self._card)
                msg = new_text_message(
                    prompt,
                    role=Role.ROLE_USER,
                    context_id=self._context_id,
                )
                final = None
                async for event in client.send_message(SendMessageRequest(message=msg)):
                    final = event
                if final is None:
                    return f"{_ERROR_PREFIX} No output from A2A agent '{self._agent_name}'"
                if final.HasField("message"):
                    from a2a.helpers.proto_helpers import (  # type: ignore[import-not-found]
                        get_message_text,
                    )

                    text = get_message_text(final.message)
                    return text or (
                        f"{_ERROR_PREFIX} No output from A2A agent '{self._agent_name}'"
                    )
                if final.HasField("task"):
                    handled = self._handle_task(final.task)
                    if handled is not None:
                        return handled
                    if not final.task.id:
                        return (
                            f"{_ERROR_PREFIX} A2A task has no ID for polling "
                            f"(agent '{self._agent_name}')"
                        )
                    return await self._poll_until_complete(client, final.task.id)
                return f"{_ERROR_PREFIX} No output from A2A agent '{self._agent_name}'"
        except A2AClientTimeoutError:
            return (
                f"{_ERROR_PREFIX} Connection timed out to A2A agent "
                f"'{self._agent_name}' at {self._base_url}"
            )
        except httpx.TimeoutException:
            return (
                f"{_ERROR_PREFIX} Connection timed out to A2A agent "
                f"'{self._agent_name}' at {self._base_url}"
            )
        except httpx.HTTPStatusError as e:
            return (
                f"{_ERROR_PREFIX} HTTP {e.response.status_code} from A2A agent "
                f"'{self._agent_name}': {e.response.text[:200]}"
            )
        except AgentCardResolutionError as e:
            return f"{_ERROR_PREFIX} Failed to resolve agent card for '{self._agent_name}': {e}"
        except A2AError as e:
            return f"{_ERROR_PREFIX} A2A JSON-RPC error from agent '{self._agent_name}': {e}"
        except A2AClientError as e:
            return f"{_ERROR_PREFIX} Failed to reach A2A agent '{self._agent_name}': {e}"
        except ValueError as e:
            return f"{_ERROR_PREFIX} Failed to reach A2A agent '{self._agent_name}': {e}"
        except Exception as e:
            return f"{_ERROR_PREFIX} Failed to reach A2A agent '{self._agent_name}': {e}"

    async def _poll_until_complete(self, client: object, task_id: str) -> str:
        """Poll ``GetTask`` until the task reaches a terminal state."""
        import anyio
        from a2a.types import GetTaskRequest  # type: ignore[import-not-found]

        deadline = anyio.current_time() + self._timeout
        delay = 0.5
        while anyio.current_time() < deadline:
            await anyio.sleep(delay)
            try:
                task = await client.get_task(GetTaskRequest(id=task_id))  # type: ignore[union-attr]
            except Exception as e:
                return f"{_ERROR_PREFIX} Error polling A2A task for agent '{self._agent_name}': {e}"
            handled = self._handle_task(task)
            if handled is not None:
                return handled
            delay = min(delay * 1.5, 5.0)
        return (
            f"{_ERROR_PREFIX} A2A task timed out for agent '{self._agent_name}' (task_id={task_id})"
        )

    def _handle_task(self, task: object) -> str | None:
        """Map a 1.0 Task to a delegate string, or None if still in progress."""
        from a2a.helpers.proto_helpers import get_message_text  # type: ignore[import-not-found]
        from a2a.types import Task, TaskState  # type: ignore[import-not-found]

        assert isinstance(task, Task)
        state = task.status.state
        if state == TaskState.TASK_STATE_COMPLETED:
            return self._extract_completed_text(task)
        if state == TaskState.TASK_STATE_FAILED:
            extra = ""
            if task.status.HasField("message"):
                extra = get_message_text(task.status.message)
            if extra:
                return f"{_ERROR_PREFIX} A2A task failed for agent '{self._agent_name}': {extra}"
            return f"{_ERROR_PREFIX} A2A task failed for agent '{self._agent_name}'"
        if state in {
            TaskState.TASK_STATE_REJECTED,
            TaskState.TASK_STATE_CANCELED,
            TaskState.TASK_STATE_AUTH_REQUIRED,
            TaskState.TASK_STATE_INPUT_REQUIRED,
        }:
            pretty = TaskState.Name(state).removeprefix("TASK_STATE_").replace("_", "-").lower()
            return f"{_ERROR_PREFIX} A2A task {pretty} for agent '{self._agent_name}'"
        if state in {TaskState.TASK_STATE_SUBMITTED, TaskState.TASK_STATE_WORKING}:
            return None
        return (
            f"{_ERROR_PREFIX} Unexpected A2A state '{TaskState.Name(state)}' "
            f"from agent '{self._agent_name}'"
        )

    def _extract_completed_text(self, task: object) -> str:
        import json as _json

        from a2a.helpers.proto_helpers import (  # type: ignore[import-not-found]
            get_data_parts,
            get_message_text,
            get_text_parts,
        )
        from a2a.types import Role, Task  # type: ignore[import-not-found]

        assert isinstance(task, Task)
        texts: list[str] = []
        for artifact in task.artifacts:
            texts.extend(get_text_parts(artifact.parts))
            for data in get_data_parts(artifact.parts):
                texts.append(_json.dumps(data))
        if texts:
            return "\n".join(texts)
        if task.status.HasField("message"):
            text = get_message_text(task.status.message)
            if text:
                return text
        for msg in reversed(task.history):
            if msg.role == Role.ROLE_AGENT:
                text = get_message_text(msg)
                if text:
                    return text
        return f"{_ERROR_PREFIX} No output from A2A agent '{self._agent_name}'"
