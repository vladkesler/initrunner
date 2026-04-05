"""MCP playground -- execute a single tool call without an LLM agent."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from initrunner._async import run_sync

if TYPE_CHECKING:
    from pathlib import Path

    from initrunner.agent.schema.security import ToolSandboxConfig
    from initrunner.agent.schema.tools import McpToolConfig


@dataclass
class PlaygroundResult:
    tool_name: str
    output: str
    duration_ms: int
    success: bool
    error: str | None


async def _execute(
    config: McpToolConfig,
    tool_name: str,
    arguments: dict,
    role_dir: Path | None = None,
    sandbox: ToolSandboxConfig | None = None,
    *,
    timeout_seconds: int = 30,
) -> PlaygroundResult:
    from fastmcp import Client  # type: ignore[import-not-found]

    from initrunner.mcp._transport import build_transport

    transport = build_transport(config, role_dir, sandbox=sandbox)

    t0 = time.monotonic()
    try:
        async with Client(transport=transport) as client:
            result = await asyncio.wait_for(
                client.call_tool(tool_name, arguments),
                timeout=timeout_seconds,
            )
        elapsed_ms = int((time.monotonic() - t0) * 1000)

        # Extract text content from the MCP CallToolResult
        parts: list[str] = []
        for item in result.content:
            text = getattr(item, "text", None)
            if text is not None:
                parts.append(text)
            else:
                parts.append(repr(item))

        return PlaygroundResult(
            tool_name=tool_name,
            output="\n".join(parts),
            duration_ms=elapsed_ms,
            success=not result.is_error,
            error="\n".join(parts) if result.is_error else None,
        )
    except Exception as exc:
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        return PlaygroundResult(
            tool_name=tool_name,
            output="",
            duration_ms=elapsed_ms,
            success=False,
            error=str(exc),
        )


def execute_tool_sync(
    config: McpToolConfig,
    tool_name: str,
    arguments: dict,
    role_dir: Path | None = None,
    sandbox: ToolSandboxConfig | None = None,
    *,
    timeout_seconds: int = 30,
) -> PlaygroundResult:
    """Sync wrapper for single MCP tool execution."""
    return run_sync(
        _execute(config, tool_name, arguments, role_dir, sandbox, timeout_seconds=timeout_seconds)
    )
