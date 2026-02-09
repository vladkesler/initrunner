"""Delegation depth tracking and agent invokers for multi-agent systems."""

from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

logger = logging.getLogger(__name__)

_ERROR_PREFIX = "[DELEGATION ERROR]"


class DelegationDepthExceeded(Exception):
    """Raised when delegation depth exceeds max_depth."""


# ---------------------------------------------------------------------------
# Thread-local delegation context
# ---------------------------------------------------------------------------

_context = threading.local()


@dataclass
class _DelegationContext:
    depth: int = 0
    chain: list[str] = field(default_factory=list)


def _get_ctx() -> _DelegationContext:
    if not hasattr(_context, "ctx"):
        _context.ctx = _DelegationContext()
    return _context.ctx


def enter_delegation(agent_name: str, max_depth: int) -> None:
    """Increment depth and push agent onto chain. Raises on depth exceeded."""
    ctx = _get_ctx()
    ctx.depth += 1
    ctx.chain.append(agent_name)
    if ctx.depth > max_depth:
        chain_str = " -> ".join(ctx.chain)
        raise DelegationDepthExceeded(
            f"Delegation depth {ctx.depth} exceeds max_depth {max_depth} (chain: {chain_str})"
        )


def exit_delegation() -> None:
    """Decrement depth and pop agent from chain."""
    ctx = _get_ctx()
    if ctx.depth > 0:
        ctx.depth -= 1
    if ctx.chain:
        ctx.chain.pop()


def get_current_depth() -> int:
    return _get_ctx().depth


def get_current_chain() -> list[str]:
    return list(_get_ctx().chain)


def reset_context() -> None:
    """Reset delegation context (for testing)."""
    ctx = _get_ctx()
    ctx.depth = 0
    ctx.chain.clear()


# ---------------------------------------------------------------------------
# Invoker protocol + implementations
# ---------------------------------------------------------------------------


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
    ) -> None:
        self._role_path = role_path
        self._max_depth = max_depth
        self._timeout = timeout
        self._shared_memory_path = shared_memory_path
        self._shared_max_memories = shared_max_memories

    def invoke(self, prompt: str) -> str:
        from initrunner.agent.executor import execute_run
        from initrunner.agent.loader import load_and_build
        from initrunner.agent.sandbox import _framework_bypass

        logger.debug("Delegating to %s (prompt=%r)", self._role_path.name, prompt[:120])

        with _framework_bypass():
            try:
                if self._shared_memory_path:
                    from initrunner.agent.loader import (
                        _load_dotenv,
                        build_agent,
                        load_role,
                    )
                    from initrunner.compose.orchestrator import apply_shared_memory

                    _load_dotenv(self._role_path.parent)
                    role = load_role(self._role_path)
                    apply_shared_memory(role, self._shared_memory_path, self._shared_max_memories)
                    # Shared memory is injected by the delegation framework from
                    # trusted coordinator YAML — relax the store-path restriction
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
            try:
                enter_delegation(agent_name, self._max_depth)
            except DelegationDepthExceeded as e:
                logger.warning("Delegation depth exceeded: %s", e)
                return f"{_ERROR_PREFIX} {e}"

            try:
                logger.debug("Executing delegate agent '%s'", agent_name)
                result, _ = execute_run(agent, role, prompt)
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
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._agent_name = agent_name
        self._timeout = timeout
        self._headers_env = headers_env or {}

    def _resolve_headers(self) -> dict[str, str]:
        """Resolve header values from environment variables."""
        headers: dict[str, str] = {}
        for header_name, env_var in self._headers_env.items():
            value = os.environ.get(env_var, "")
            if value:
                headers[header_name] = value
        return headers

    def invoke(self, prompt: str) -> str:
        import httpx

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
                data = resp.json()
                return data["choices"][0]["message"]["content"]
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
