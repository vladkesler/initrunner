"""Tool call permission checker and toolset wrapper.

Provides declarative allow/deny rules evaluated against tool call arguments
using ``fnmatch`` glob patterns.  Deny rules are evaluated first (deny wins),
then allow rules, then the configured default.
"""

from __future__ import annotations

import fnmatch
from collections.abc import Iterator
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pydantic_ai.toolsets.abstract import ToolsetTool

from pydantic_ai.toolsets import AbstractToolset

from initrunner.agent.schema.tools import ToolPermissions

_UNSET = object()


def _iter_leaf_values(value: Any) -> Iterator[str]:
    """Yield every scalar leaf in *value* (recursing dicts/lists/tuples/sets) as a string.

    Recursion + stringification is a security requirement: a deny rule must not
    be silently bypassable by nesting a sensitive value inside a dict/list
    argument or by passing it as a non-string scalar.
    """
    if isinstance(value, dict):
        for sub in value.values():
            yield from _iter_leaf_values(sub)
    elif isinstance(value, (list, tuple, set)):
        for item in value:
            yield from _iter_leaf_values(item)
    elif value is not None:
        yield str(value)


def _resolve_arg(tool_args: dict[str, Any], arg_name: str) -> Any:
    """Resolve a (possibly dotted, e.g. ``options.path``) *arg_name* into nested args."""
    current: Any = tool_args
    for part in arg_name.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return _UNSET
    return current


def _matches(pattern: str, tool_args: dict[str, Any]) -> bool:
    """Return True if *pattern* matches any value in *tool_args*.

    Pattern format:
    - ``arg_name=glob`` -- match *glob* against ``tool_args[arg_name]``. ``arg_name``
      may be dotted (``options.path``) to target a nested value. The value is
      searched leaf-by-leaf, so dict/list arguments and non-string scalars are
      covered.
    - bare glob (no ``=``) -- match against every (recursively nested) value in
      *tool_args*, stringifying non-strings.
    """
    if "=" in pattern:
        arg_name, _, glob = pattern.partition("=")
        value = _resolve_arg(tool_args, arg_name)
        if value is _UNSET:
            return False
        return any(fnmatch.fnmatch(leaf, glob) for leaf in _iter_leaf_values(value))

    return any(
        fnmatch.fnmatch(leaf, pattern)
        for value in tool_args.values()
        for leaf in _iter_leaf_values(value)
    )


def check_tool_permission(
    tool_args: dict[str, Any],
    permissions: ToolPermissions,
) -> tuple[bool, str]:
    """Check whether a tool call is allowed.

    Returns:
        A ``(allowed, matched_pattern)`` tuple.  *matched_pattern* is the
        rule that decided the outcome (empty string when the default wins).
    """
    # Deny rules checked first -- deny wins
    for pattern in permissions.deny:
        if _matches(pattern, tool_args):
            return False, pattern

    # Allow rules
    for pattern in permissions.allow:
        if _matches(pattern, tool_args):
            return True, pattern

    # Fall back to default
    return permissions.default == "allow", ""


class PermissionToolset(AbstractToolset[Any]):
    """Wraps an inner toolset and enforces argument-level permission rules."""

    def __init__(
        self,
        inner: AbstractToolset[Any],
        permissions: ToolPermissions,
        tool_type: str,
    ) -> None:
        self._inner = inner
        self._permissions = permissions
        self._tool_type = tool_type

    @property
    def id(self) -> str | None:
        return self._inner.id

    async def get_tools(self, ctx: Any) -> dict[str, ToolsetTool[Any]]:
        return await self._inner.get_tools(ctx)

    async def call_tool(
        self,
        name: str,
        tool_args: dict[str, Any],
        ctx: Any,
        tool: ToolsetTool[Any],
    ) -> Any:
        allowed, matched = check_tool_permission(tool_args, self._permissions)
        if not allowed:
            rule_info = (
                f" -- blocked by rule: {matched}" if matched else " -- blocked by default policy"
            )
            return f"Permission denied: {name}{rule_info}"
        return await self._inner.call_tool(name, tool_args, ctx, tool)

    async def __aenter__(self) -> PermissionToolset:
        await self._inner.__aenter__()
        return self

    async def __aexit__(self, *args: Any) -> bool | None:
        return await self._inner.__aexit__(*args)


class PolicyToolset(AbstractToolset[Any]):
    """Checks policy-based tool-level authorization per call using agent principals.

    Reads the agent principal and policy engine from ContextVars (set per-run
    by the executor).  No-op when: engine is None (policies disabled), agent
    principal is None, or ``agent_checks`` is False.
    """

    def __init__(
        self,
        inner: AbstractToolset[Any],
        tool_type: str,
        agent_name: str,
        *,
        instance_key: str = "",
    ) -> None:
        self._inner = inner
        self._tool_type = tool_type
        self._agent_name = agent_name
        self._instance_key = instance_key

    @property
    def id(self) -> str | None:
        return self._inner.id

    async def get_tools(self, ctx: Any) -> dict[str, ToolsetTool[Any]]:
        return await self._inner.get_tools(ctx)

    async def call_tool(
        self,
        name: str,
        tool_args: dict[str, Any],
        ctx: Any,
        tool: ToolsetTool[Any],
    ) -> Any:
        from initrunner.agent.executor_auth import _cached_config
        from initrunner.authz import EXECUTE, TOOL, get_current_agent_principal, get_current_engine

        engine = get_current_engine()
        principal = get_current_agent_principal()
        agent_checks = getattr(_cached_config, "agent_checks", False)

        if engine is not None and agent_checks and principal is not None:
            resource_attrs: dict[str, Any] = {
                "tool_type": self._tool_type,
                "agent": self._agent_name,
                "callable": name,
            }
            if self._instance_key:
                resource_attrs["instance"] = self._instance_key

            decision = await engine.check_async(
                principal,
                TOOL,
                EXECUTE,
                resource_id=name,
                resource_attrs=resource_attrs,
            )
            if not decision.allowed:
                msg = f"Permission denied: {name} -- {decision.reason}"
                if decision.advice:
                    msg += f" ({decision.advice})"
                return msg

        return await self._inner.call_tool(name, tool_args, ctx, tool)

    async def __aenter__(self) -> PolicyToolset:
        await self._inner.__aenter__()
        return self

    async def __aexit__(self, *args: Any) -> bool | None:
        return await self._inner.__aexit__(*args)
