"""Web search tool: search the web and news via multiple providers."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from pydantic_ai.toolsets.function import FunctionToolset

from initrunner.agent._env import resolve_env_vars
from initrunner.agent._truncate import truncate_output
from initrunner.agent.schema.tools import SearchToolConfig
from initrunner.agent.tools._registry import register_tool

if TYPE_CHECKING:
    from initrunner.agent.tools._registry import ToolBuildContext

logger = logging.getLogger(__name__)

_MAX_SEARCH_BYTES = 65_536


# ---------------------------------------------------------------------------
# Provider implementations
# ---------------------------------------------------------------------------


def _search_duckduckgo(
    query: str,
    max_results: int,
    safe_search: bool,
    api_key: str,
    timeout: int,
    news: bool = False,
    days_back: int = 7,
) -> list[dict[str, str]]:
    """Search using DuckDuckGo (free, no API key required)."""
    try:
        from duckduckgo_search import DDGS  # type: ignore[import-not-found]
    except ImportError:
        raise ImportError("duckduckgo-search is required: pip install initrunner[search]") from None

    safesearch = "moderate" if safe_search else "off"

    with DDGS() as ddgs:
        if news:
            if days_back <= 1:
                timelimit = "d"
            elif days_back <= 7:
                timelimit = "w"
            else:
                timelimit = "m"
            raw = list(
                ddgs.news(
                    query, max_results=max_results, timelimit=timelimit, safesearch=safesearch
                )
            )
            return [
                {
                    "title": r.get("title", ""),
                    "url": r.get("url", ""),
                    "snippet": r.get("body", ""),
                }
                for r in raw
            ]
        else:
            raw = list(ddgs.text(query, max_results=max_results, safesearch=safesearch))
            return [
                {
                    "title": r.get("title", ""),
                    "url": r.get("href", ""),
                    "snippet": r.get("body", ""),
                }
                for r in raw
            ]


def _search_serpapi(
    query: str,
    max_results: int,
    safe_search: bool,
    api_key: str,
    timeout: int,
    news: bool = False,
    days_back: int = 7,
) -> list[dict[str, str]]:
    """Search using SerpAPI (requires API key)."""
    import httpx

    engine = "google_news" if news else "google"
    params = {
        "q": query,
        "num": max_results,
        "api_key": api_key,
        "safe": "active" if safe_search else "off",
        "engine": engine,
    }

    with httpx.Client(timeout=timeout) as client:
        resp = client.get("https://serpapi.com/search", params=params)
        resp.raise_for_status()
        data = resp.json()

    results = data.get("organic_results", [])
    return [
        {
            "title": r.get("title", ""),
            "url": r.get("link", ""),
            "snippet": r.get("snippet", ""),
        }
        for r in results[:max_results]
    ]


def _search_brave(
    query: str,
    max_results: int,
    safe_search: bool,
    api_key: str,
    timeout: int,
    news: bool = False,
    days_back: int = 7,
) -> list[dict[str, str]]:
    """Search using Brave Search API (requires API key)."""
    import httpx

    base = "https://api.search.brave.com/res/v1"
    url = f"{base}/news/search" if news else f"{base}/web/search"
    headers = {
        "X-Subscription-Token": api_key,
        "Accept": "application/json",
    }
    params = {
        "q": query,
        "count": max_results,
        "safesearch": "moderate" if safe_search else "off",
    }

    with httpx.Client(timeout=timeout) as client:
        resp = client.get(url, headers=headers, params=params)
        resp.raise_for_status()
        data = resp.json()

    if news:
        results = data.get("results", [])
    else:
        results = data.get("web", {}).get("results", [])

    return [
        {
            "title": r.get("title", ""),
            "url": r.get("url", ""),
            "snippet": r.get("description", ""),
        }
        for r in results[:max_results]
    ]


def _search_tavily(
    query: str,
    max_results: int,
    safe_search: bool,
    api_key: str,
    timeout: int,
    news: bool = False,
    days_back: int = 7,
) -> list[dict[str, str]]:
    """Search using Tavily API (requires API key)."""
    import httpx

    body = {
        "query": query,
        "max_results": max_results,
        "api_key": api_key,
        "topic": "news" if news else "general",
    }

    with httpx.Client(timeout=timeout) as client:
        resp = client.post("https://api.tavily.com/search", json=body)
        resp.raise_for_status()
        data = resp.json()

    results = data.get("results", [])
    return [
        {
            "title": r.get("title", ""),
            "url": r.get("url", ""),
            "snippet": r.get("content", ""),
        }
        for r in results[:max_results]
    ]


_PROVIDERS = {
    "duckduckgo": _search_duckduckgo,
    "serpapi": _search_serpapi,
    "brave": _search_brave,
    "tavily": _search_tavily,
}


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------


def _format_results(results: list[dict[str, str]]) -> str:
    """Format search results as a numbered list."""
    if not results:
        return "No results found."

    lines: list[str] = []
    for i, r in enumerate(results, 1):
        title = r.get("title", "(no title)")
        url = r.get("url", "")
        snippet = r.get("snippet", "")
        lines.append(f"{i}. **{title}**\n   {url}\n   {snippet}\n")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------


@register_tool("search", SearchToolConfig)
def build_search_toolset(
    config: SearchToolConfig,
    ctx: ToolBuildContext,
) -> FunctionToolset:
    """Build a FunctionToolset for web and news search."""
    api_key = resolve_env_vars(config.api_key)
    provider_fn = _PROVIDERS[config.provider]

    toolset = FunctionToolset()

    @toolset.tool
    def web_search(query: str, num_results: int = 5) -> str:
        """Search the web for information.

        Args:
            query: The search query string.
            num_results: Maximum number of results to return (default 5).
        """
        try:
            results = provider_fn(
                query=query,
                max_results=min(num_results, config.max_results),
                safe_search=config.safe_search,
                api_key=api_key,
                timeout=config.timeout_seconds,
                news=False,
            )
            return truncate_output(_format_results(results), _MAX_SEARCH_BYTES)
        except ImportError as e:
            return f"Error: {e}"
        except TimeoutError:
            return f"Error: search timed out after {config.timeout_seconds}s"
        except Exception as e:
            return f"Error: search failed: {e}"

    @toolset.tool
    def news_search(query: str, num_results: int = 5, days_back: int = 7) -> str:
        """Search for recent news articles.

        Args:
            query: The search query string.
            num_results: Maximum number of results to return (default 5).
            days_back: How many days back to search (default 7).
        """
        try:
            results = provider_fn(
                query=query,
                max_results=min(num_results, config.max_results),
                safe_search=config.safe_search,
                api_key=api_key,
                timeout=config.timeout_seconds,
                news=True,
                days_back=days_back,
            )
            return truncate_output(_format_results(results), _MAX_SEARCH_BYTES)
        except ImportError as e:
            return f"Error: {e}"
        except TimeoutError:
            return f"Error: search timed out after {config.timeout_seconds}s"
        except Exception as e:
            return f"Error: search failed: {e}"

    return toolset
