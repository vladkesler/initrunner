"""HTTP request tools."""

from __future__ import annotations

import httpx
from pydantic_ai.toolsets.function import FunctionToolset

from initrunner.agent._truncate import truncate_output
from initrunner.agent._urls import SSRFBlocked, SSRFSafeTransport
from initrunner.agent.schema.tools import HttpToolConfig
from initrunner.agent.tools._registry import ToolBuildContext, register_tool

_MAX_HTTP_RESPONSE_BYTES = 102_400  # 100 KB


@register_tool("http", HttpToolConfig)
def build_http_toolset(config: HttpToolConfig, ctx: ToolBuildContext) -> FunctionToolset:
    """Build a FunctionToolset for HTTP requests."""
    allowed_methods = {m.upper() for m in config.allowed_methods}

    toolset = FunctionToolset()

    @toolset.tool
    def http_request(method: str, path: str, body: str = "") -> str:
        """Make an HTTP request to the configured base URL."""
        method = method.upper()
        if method not in allowed_methods:
            return f"Error: HTTP method {method} is not allowed"
        url = f"{config.base_url.rstrip('/')}/{path.lstrip('/')}"
        try:
            with httpx.Client(
                headers=config.headers,
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

    return toolset
