"""Web reader tool: fetch pages and convert to markdown."""

from __future__ import annotations

from pydantic_ai.toolsets.function import FunctionToolset

from initrunner.agent._urls import SSRFBlocked, check_domain_filter
from initrunner.agent.schema.tools import WebReaderToolConfig
from initrunner.agent.tools._registry import ToolBuildContext, register_tool


def _fetch_page_sync(url: str, config: WebReaderToolConfig) -> str:
    """Fetch a page synchronously, returning markdown or an error string."""
    error = check_domain_filter(url, config.allowed_domains, config.blocked_domains)
    if error:
        return error
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


async def _fetch_page_async(url: str, config: WebReaderToolConfig) -> str:
    """Fetch a page asynchronously, returning markdown or an error string."""
    error = check_domain_filter(url, config.allowed_domains, config.blocked_domains)
    if error:
        return error
    try:
        from initrunner._html import fetch_url_as_markdown_async

        return await fetch_url_as_markdown_async(
            url,
            timeout=config.timeout_seconds,
            user_agent=config.user_agent,
            max_bytes=config.max_content_bytes,
        )
    except SSRFBlocked as e:
        return str(e)
    except Exception as e:
        return f"Error fetching URL: {e}"


@register_tool("web_reader", WebReaderToolConfig)
def build_web_reader_toolset(config: WebReaderToolConfig, ctx: ToolBuildContext) -> FunctionToolset:
    """Build a FunctionToolset for fetching and reading web pages."""
    toolset = FunctionToolset()

    if ctx.prefer_async:

        @toolset.tool_plain
        async def fetch_page(url: str) -> str:
            """Fetch a web page and return its content as markdown."""
            return await _fetch_page_async(url, config)

    else:

        @toolset.tool_plain
        def fetch_page(url: str) -> str:
            """Fetch a web page and return its content as markdown."""
            return _fetch_page_sync(url, config)

    return toolset
