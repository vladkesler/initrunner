"""Shared HTML fetch + markdown conversion utility."""

from __future__ import annotations

import httpx
import markdownify
from bs4 import BeautifulSoup

from initrunner import __version__
from initrunner.agent._truncate import truncate_output
from initrunner.agent._urls import SSRFSafeTransport

_USER_AGENT = f"initrunner/{__version__}"


def fetch_url_as_markdown(
    url: str,
    *,
    timeout: int = 15,
    user_agent: str = _USER_AGENT,
    max_bytes: int = 512_000,
) -> str:
    """Fetch a URL with SSRF protection and convert HTML to markdown.

    Non-HTML content is returned as plain text, truncated to *max_bytes*.
    """
    with httpx.Client(
        timeout=timeout,
        headers={"User-Agent": user_agent},
        follow_redirects=True,
        transport=SSRFSafeTransport(),
    ) as client:
        resp = client.get(url)
        resp.raise_for_status()

    content_type = resp.headers.get("content-type", "")
    if "html" not in content_type:
        return truncate_output(resp.text, max_bytes)

    soup = BeautifulSoup(resp.text, "html.parser")

    # Strip script, style, noscript tags
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    # Strip inline base64 data URIs
    for tag in soup.find_all(src=True):
        if tag["src"].startswith("data:"):  # type: ignore[union-attr]
            tag.decompose()
    for tag in soup.find_all(href=True):
        if tag["href"].startswith("data:"):  # type: ignore[union-attr]
            tag.decompose()

    md = markdownify.markdownify(str(soup), strip=["img"])
    return truncate_output(md, max_bytes)
