"""Web reader tool: fetch pages and convert to markdown."""

from __future__ import annotations

from pydantic_ai.toolsets.function import FunctionToolset

from initrunner.agent._urls import SSRFBlocked, check_domain_filter
from initrunner.agent.schema.tools import WebReaderToolConfig
from initrunner.agent.tools._registry import ToolBuildContext, register_tool


@register_tool("web_reader", WebReaderToolConfig)
def build_web_reader_toolset(config: WebReaderToolConfig, ctx: ToolBuildContext) -> FunctionToolset:
    """Build a FunctionToolset for fetching and reading web pages."""
    toolset = FunctionToolset()

    if ctx.prefer_async:

        @toolset.tool
        async def fetch_page(url: str) -> str:
            """Fetch a web page and return its content as markdown."""
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

    else:

        @toolset.tool
        def fetch_page(url: str) -> str:
            """Fetch a web page and return its content as markdown."""
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

    return toolset
