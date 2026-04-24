"""Human-in-the-loop approval gating.

Wraps an inner toolset so every tool definition it exposes is marked
``kind="unapproved"``.  PydanticAI routes calls to unapproved tools into
:class:`~pydantic_ai.DeferredToolRequests` instead of executing them; the
caller collects approval out-of-band and resumes the run with
:class:`~pydantic_ai.DeferredToolResults`.

This is a pure build-time flag — there is no runtime intercept.  Permission
and policy gating (deny-rules, Cedar) run first in the wrapper stack, so a
call that would be denied never reaches the human approver.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, Any

from pydantic_ai.toolsets import AbstractToolset

if TYPE_CHECKING:
    from pydantic_ai.toolsets.abstract import ToolsetTool


class ApprovalToolset(AbstractToolset[Any]):
    """Marks every wrapped tool as requiring human approval."""

    def __init__(self, inner: AbstractToolset[Any], tool_type: str) -> None:
        self._inner = inner
        self._tool_type = tool_type

    @property
    def id(self) -> str | None:
        return self._inner.id

    async def get_tools(self, ctx: Any) -> dict[str, ToolsetTool[Any]]:
        tools = await self._inner.get_tools(ctx)
        return {
            name: replace(t, tool_def=replace(t.tool_def, kind="unapproved"))
            for name, t in tools.items()
        }

    async def call_tool(
        self,
        name: str,
        tool_args: dict[str, Any],
        ctx: Any,
        tool: ToolsetTool[Any],
    ) -> Any:
        return await self._inner.call_tool(name, tool_args, ctx, tool)

    async def __aenter__(self) -> ApprovalToolset:
        await self._inner.__aenter__()
        return self

    async def __aexit__(self, *args: Any) -> bool | None:
        return await self._inner.__aexit__(*args)
