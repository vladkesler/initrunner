"""Web reader tool: fetch pages and convert to markdown."""

from __future__ import annotations

from pydantic_ai.toolsets.function import FunctionToolset

from initrunner.agent._urls import SSRFBlocked
from initrunner.agent.schema import WebReaderToolConfig
from initrunner.agent.tools._registry import ToolBuildContext, register_tool


@register_tool("web_reader", WebReaderToolConfig)
def build_web_reader_toolset(config: WebReaderToolConfig, ctx: ToolBuildContext) -> FunctionToolset:
    """Build a FunctionToolset for fetching and reading web pages."""
    from urllib.parse import urlparse

    toolset = FunctionToolset()

    @toolset.tool
    def fetch_page(url: str) -> str:
        """Fetch a web page and return its content as markdown."""
        try:
            parsed = urlparse(url)
            hostname = parsed.hostname or ""
        except Exception:
            return "Error: invalid URL"

        if config.allowed_domains:
            if hostname not in config.allowed_domains:
                return f"Error: domain '{hostname}' is not in the allowed domains list"
        elif config.blocked_domains:
            if hostname in config.blocked_domains:
                return f"Error: domain '{hostname}' is blocked"

        try:
            from initrunner._html import fetch_url_as_markdown

            return fetch_url_as_markdown(
                url,
                timeout=config.timeout_seconds,
                user_agent=config.user_agent,
                max_bytes=config.max_content_bytes,
            )
        except SSRFBlocked as e:
            return str(e)
        except Exception as e:
            return f"Error fetching URL: {e}"

    return toolset
