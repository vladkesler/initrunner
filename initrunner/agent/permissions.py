"""Tool call permission checker and toolset wrapper.

Provides declarative allow/deny rules evaluated against tool call arguments
using ``fnmatch`` glob patterns.  Deny rules are evaluated first (deny wins),
then allow rules, then the configured default.
"""

from __future__ import annotations

import fnmatch
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pydantic_ai.toolsets.abstract import ToolsetTool

from pydantic_ai.toolsets import AbstractToolset

from initrunner.agent.schema.tools import ToolPermissions


def _matches(pattern: str, tool_args: dict[str, Any]) -> bool:
    """Return True if *pattern* matches any value in *tool_args*.

    Pattern format:
    - ``arg_name=glob`` — match *glob* against ``tool_args[arg_name]``
    - bare glob (no ``=``) — match against every string value in *tool_args*
    """
    if "=" in pattern:
        arg_name, _, glob = pattern.partition("=")
        value = tool_args.get(arg_name)
        if value is None:
            return False
        return fnmatch.fnmatch(str(value), glob)

    # Bare pattern: match against all string values
    for value in tool_args.values():
        if isinstance(value, str) and fnmatch.fnmatch(value, pattern):
            return True
    return False


def check_tool_permission(
    tool_args: dict[str, Any],
    permissions: ToolPermissions,
) -> tuple[bool, str]:
    """Check whether a tool call is allowed.

    Returns:
        A ``(allowed, matched_pattern)`` tuple.  *matched_pattern* is the
        rule that decided the outcome (empty string when the default wins).
    """
    # Deny rules checked first — deny wins
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
                f" — blocked by rule: {matched}" if matched else " — blocked by default policy"
            )
            return f"Permission denied: {name}{rule_info}"
        return await self._inner.call_tool(name, tool_args, ctx, tool)

    async def __aenter__(self) -> PermissionToolset:
        await self._inner.__aenter__()
        return self

    async def __aexit__(self, *args: Any) -> bool | None:
        return await self._inner.__aexit__(*args)


class CerbosToolset(AbstractToolset[Any]):
    """Checks Cerbos tool-level authorization per call.

    Reads principal and authz from ContextVars (set per-request by the call
    site). No-op when: authz is None (Cerbos disabled), principal is None
    (CLI/trigger -- no HTTP identity), or tool_checks_enabled is False.
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
        from initrunner.authz import EXECUTE, TOOL, get_current_authz, get_current_principal

        authz = get_current_authz()
        principal = get_current_principal()

        if authz is not None and authz.tool_checks_enabled and principal is not None:
            resource_attrs: dict[str, Any] = {
                "tool_type": self._tool_type,
                "agent": self._agent_name,
                "callable": name,
            }
            if self._instance_key:
                resource_attrs["instance"] = self._instance_key

            allowed = await authz.check_async(
                principal,
                TOOL,
                EXECUTE,
                resource_id=name,
                resource_attrs=resource_attrs,
            )
            if not allowed:
                return f"Permission denied: {name} -- blocked by policy"

        return await self._inner.call_tool(name, tool_args, ctx, tool)

    async def __aenter__(self) -> CerbosToolset:
        await self._inner.__aenter__()
        return self

    async def __aexit__(self, *args: Any) -> bool | None:
        return await self._inner.__aexit__(*args)
