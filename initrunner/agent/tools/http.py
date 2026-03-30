"""HTTP request tools."""

from __future__ import annotations

import httpx
from pydantic_ai.toolsets.function import FunctionToolset

from initrunner.agent._truncate import truncate_output
from initrunner.agent._urls import AsyncSSRFSafeTransport, SSRFBlocked, SSRFSafeTransport
from initrunner.agent.schema.tools import HttpToolConfig
from initrunner.agent.tools._registry import ToolBuildContext, register_tool

_MAX_HTTP_RESPONSE_BYTES = 102_400  # 100 KB


def _do_http_request(
    method: str,
    path: str,
    body: str,
    base_url: str,
    headers: dict[str, str],
    allowed_methods: set[str],
) -> str:
    """Execute a sync HTTP request, returning a formatted response or error."""
    method = method.upper()
    if method not in allowed_methods:
        return f"Error: HTTP method {method} is not allowed"
    url = f"{base_url.rstrip('/')}/{path.lstrip('/')}"
    try:
        with httpx.Client(
            headers=headers,
            timeout=30,
            transport=SSRFSafeTransport(),
        ) as client:
            resp = client.request(method, url, content=body if body else None)
            text = truncate_output(resp.text, _MAX_HTTP_RESPONSE_BYTES)
            return f"HTTP {resp.status_code}\n{text}"
    except SSRFBlocked as e:
        return str(e)
    except httpx.HTTPError as e:
        return f"HTTP error: {e}"


async def _do_http_request_async(
    method: str,
    path: str,
    body: str,
    base_url: str,
    headers: dict[str, str],
    allowed_methods: set[str],
) -> str:
    """Execute an async HTTP request, returning a formatted response or error."""
    method = method.upper()
    if method not in allowed_methods:
        return f"Error: HTTP method {method} is not allowed"
    url = f"{base_url.rstrip('/')}/{path.lstrip('/')}"
    try:
        async with httpx.AsyncClient(
            headers=headers,
            timeout=30,
            transport=AsyncSSRFSafeTransport(),
        ) as client:
            resp = await client.request(method, url, content=body if body else None)
            text = truncate_output(resp.text, _MAX_HTTP_RESPONSE_BYTES)
            return f"HTTP {resp.status_code}\n{text}"
    except SSRFBlocked as e:
        return str(e)
    except httpx.HTTPError as e:
        return f"HTTP error: {e}"


@register_tool("http", HttpToolConfig)
def build_http_toolset(config: HttpToolConfig, ctx: ToolBuildContext) -> FunctionToolset:
    """Build a FunctionToolset for HTTP requests."""
    allowed_methods = {m.upper() for m in config.allowed_methods}

    toolset = FunctionToolset()

    if ctx.prefer_async:

        @toolset.tool_plain
        async def http_request(method: str, path: str, body: str = "") -> str:
            """Make an HTTP request to the configured base URL."""
            return await _do_http_request_async(
                method, path, body, config.base_url, config.headers, allowed_methods
            )

    else:

        @toolset.tool_plain
        def http_request(method: str, path: str, body: str = "") -> str:
            """Make an HTTP request to the configured base URL."""
            return _do_http_request(
                method, path, body, config.base_url, config.headers, allowed_methods
            )

    return toolset
