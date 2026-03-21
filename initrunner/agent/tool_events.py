"""Observable tool wrapper: ContextVar-based tool call status events."""

from __future__ import annotations

import contextvars
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from pydantic_ai.toolsets import AbstractToolset

if TYPE_CHECKING:
    from pydantic_ai.toolsets.abstract import ToolsetTool


@dataclass(frozen=True, slots=True)
class ToolEvent:
    """Represents a completed tool call."""

    tool_name: str
    status: str  # "ok" or "error"
    error_summary: str | None
    duration_ms: int


# ---------------------------------------------------------------------------
# ContextVar plumbing
# ---------------------------------------------------------------------------

_tool_event_callback: contextvars.ContextVar[Callable[[ToolEvent], None] | None] = (
    contextvars.ContextVar("_tool_event_callback", default=None)
)


def set_tool_event_callback(
    cb: Callable[[ToolEvent], None] | None,
) -> contextvars.Token[Callable[[ToolEvent], None] | None]:
    """Set the tool event callback for the current context."""
    return _tool_event_callback.set(cb)


def reset_tool_event_callback(
    token: contextvars.Token[Callable[[ToolEvent], None] | None],
) -> None:
    """Reset the tool event callback to its previous value."""
    _tool_event_callback.reset(token)


def get_tool_event_callback() -> Callable[[ToolEvent], None] | None:
    """Read the current tool event callback."""
    return _tool_event_callback.get()


# ---------------------------------------------------------------------------
# Error detection
# ---------------------------------------------------------------------------

_ERROR_PREFIXES = (
    "Error",
    "HTTP error:",
    "Permission denied:",
    "SSRF blocked:",
    "Exit code:",
    "Execution timed out after",
)


def _is_error_result(result: Any) -> str | None:
    """Detect if a tool return value represents an error.

    Returns the first line (truncated to 120 chars) if error, else ``None``.
    """
    if not isinstance(result, str):
        return None
    for prefix in _ERROR_PREFIXES:
        if result.startswith(prefix):
            first_line = result.split("\n", 1)[0]
            return first_line[:120]
    return None


# ---------------------------------------------------------------------------
# ObservableToolset wrapper
# ---------------------------------------------------------------------------


class ObservableToolset(AbstractToolset[Any]):
    """Outermost toolset wrapper that emits ToolEvents via ContextVar callback.

    Zero overhead when no callback is set (the default path).
    """

    def __init__(self, inner: AbstractToolset[Any]) -> None:
        self._inner = inner

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
        callback = _tool_event_callback.get()
        if callback is None:
            return await self._inner.call_tool(name, tool_args, ctx, tool)

        start = time.monotonic()
        result = await self._inner.call_tool(name, tool_args, ctx, tool)
        duration_ms = int((time.monotonic() - start) * 1000)

        error_summary = _is_error_result(result)
        event = ToolEvent(
            tool_name=name,
            status="error" if error_summary else "ok",
            error_summary=error_summary,
            duration_ms=duration_ms,
        )
        try:
            callback(event)
        except Exception:
            pass  # callback failures must not crash agent runs

        return result

    async def __aenter__(self) -> ObservableToolset:
        await self._inner.__aenter__()
        return self

    async def __aexit__(self, *args: Any) -> bool | None:
        return await self._inner.__aexit__(*args)


def wrap_observable(toolset: AbstractToolset[Any]) -> ObservableToolset:
    """Idempotent helper -- wraps *toolset* unless it is already observable."""
    if isinstance(toolset, ObservableToolset):
        return toolset
    return ObservableToolset(toolset)
