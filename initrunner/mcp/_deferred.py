"""Deferred MCP toolset -- serves cached schemas until first tool call."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any, Self

from pydantic_ai.tools import ToolDefinition
from pydantic_ai.toolsets.abstract import AbstractToolset, ToolsetTool
from pydantic_ai.toolsets.fastmcp import FastMCPToolset

from initrunner.mcp._cache import CachedTool, diff_schemas, write_cache

_logger = logging.getLogger(__name__)

# Lazy import to avoid pulling in mcp when not needed.
_SCHEMA_VALIDATOR: Any = None


def _get_schema_validator() -> Any:
    global _SCHEMA_VALIDATOR
    if _SCHEMA_VALIDATOR is None:
        from pydantic_ai.mcp import TOOL_SCHEMA_VALIDATOR

        _SCHEMA_VALIDATOR = TOOL_SCHEMA_VALIDATOR
    return _SCHEMA_VALIDATOR


class DeferredMcpToolset(AbstractToolset[Any]):
    """Lazy MCP toolset: serves cached schemas until first ``call_tool``.

    Three states:

    * **Cache hit, not connected** -- ``get_tools`` returns cached
      ``ToolDefinition``s; ``call_tool`` triggers lazy connect.
    * **Cache miss, not connected** -- ``get_tools`` connects eagerly
      (first run for this server), caches schemas, serves live.
    * **Connected** -- delegates entirely to the live ``FastMCPToolset``.
    """

    def __init__(
        self,
        cached_defs: list[ToolDefinition] | None,
        factory: Callable[[], FastMCPToolset],
        cache_key: str,
        max_retries: int = 1,
    ) -> None:
        self._cached_defs = cached_defs
        self._factory = factory
        self._cache_key = cache_key
        self._max_retries = max_retries
        self._live: FastMCPToolset | None = None
        self._connect_lock = asyncio.Lock()

    @property
    def id(self) -> str | None:
        return f"deferred-mcp-{self._cache_key}"

    # -- Lifecycle ------------------------------------------------------------

    async def __aenter__(self) -> Self:
        return self  # no-op: the whole point is to defer connection

    async def __aexit__(self, *args: Any) -> bool | None:
        if self._live is not None:
            await self._live.__aexit__(*args)
            self._live = None
        return None

    # -- Tool listing ---------------------------------------------------------

    async def get_tools(self, ctx: Any) -> dict[str, ToolsetTool[Any]]:
        if self._live is not None:
            return await self._live.get_tools(ctx)
        if self._cached_defs is not None:
            return {td.name: self._stub_tool(td) for td in self._cached_defs}
        # Cache miss: connect eagerly this one time, cache for future runs.
        await self._connect()
        return await self._live.get_tools(ctx)  # type: ignore[union-attr]

    # -- Tool execution -------------------------------------------------------

    async def call_tool(
        self,
        name: str,
        tool_args: dict[str, Any],
        ctx: Any,
        tool: ToolsetTool[Any],
    ) -> Any:
        if self._live is None:
            await self._connect()
        return await self._live.call_tool(name, tool_args, ctx, tool)  # type: ignore[union-attr]

    # -- Internal -------------------------------------------------------------

    def _stub_tool(self, td: ToolDefinition) -> ToolsetTool[Any]:
        """Build a ``ToolsetTool`` from a cached ``ToolDefinition``."""
        return ToolsetTool(
            tool_def=td,
            toolset=self,
            max_retries=self._max_retries,
            args_validator=_get_schema_validator(),
        )

    async def _connect(self) -> None:
        """Create the live toolset, check for schema drift, update cache."""
        async with self._connect_lock:
            if self._live is not None:
                return  # another coroutine connected while we waited

            live = self._factory()
            await live.__aenter__()
            self._live = live

            # Fetch live schemas and update cache.
            try:
                mcp_tools = await live.client.list_tools()
            except Exception:
                _logger.debug("Failed to list tools for cache update on %s", self._cache_key)
                return

            live_cached = [
                CachedTool(
                    name=t.name,
                    description=t.description or "",
                    parameters_json_schema=t.inputSchema,
                    metadata={
                        "meta": t.meta,
                        "annotations": (t.annotations.model_dump() if t.annotations else None),
                        "output_schema": t.outputSchema or None,
                    },
                )
                for t in mcp_tools
            ]

            # Schema drift detection.
            if self._cached_defs is not None:
                old_cached = [
                    CachedTool(
                        name=td.name,
                        description=td.description,
                        parameters_json_schema=td.parameters_json_schema,
                        metadata=td.metadata,
                    )
                    for td in self._cached_defs
                ]
                for msg in diff_schemas(old_cached, live_cached):
                    _logger.warning("MCP schema drift [%s]: %s", self._cache_key, msg)

            write_cache(self._cache_key, live_cached)
