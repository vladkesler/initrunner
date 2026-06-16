"""Shared HTML fetch + markdown conversion utility."""

from __future__ import annotations

import httpx
import markdownify
from bs4 import BeautifulSoup

from initrunner import __version__
from initrunner.agent._truncate import truncate_output
from initrunner.agent._urls import AsyncSSRFSafeTransport, SSRFSafeTransport

_USER_AGENT = f"initrunner/{__version__}"


def _decode_capped_body(body: bytes, encoding: str | None) -> str:
    """Decode *body* using *encoding* (header charset), falling back to UTF-8."""
    try:
        return body.decode(encoding or "utf-8", errors="replace")
    except LookupError:
        return body.decode("utf-8", errors="replace")


def _read_body_capped(resp: httpx.Response, max_bytes: int) -> str:
    """Read a streamed response body up to a hard byte ceiling, then decode.

    Bounds memory: at most ~``max_bytes`` are ever held regardless of the
    server's ``Content-Length`` (which may lie) or chunked/compressed size.
    """
    body = bytearray()
    for chunk in resp.iter_bytes():
        body.extend(chunk)
        if len(body) >= max_bytes:
            break
    return _decode_capped_body(bytes(body), resp.encoding)


async def _read_body_capped_async(resp: httpx.Response, max_bytes: int) -> str:
    """Async variant of :func:`_read_body_capped`."""
    body = bytearray()
    async for chunk in resp.aiter_bytes():
        body.extend(chunk)
        if len(body) >= max_bytes:
            break
    return _decode_capped_body(bytes(body), resp.encoding)


def _response_to_markdown(text: str, content_type: str, max_bytes: int) -> str:
    """Convert a (already byte-capped) response body to markdown, stripping unsafe HTML.

    Non-HTML content is returned as truncated plain text.
    """
    if "html" not in content_type:
        return truncate_output(text, max_bytes)

    soup = BeautifulSoup(text, "html.parser")

    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    for tag in soup.find_all(src=True):
        if tag["src"].startswith("data:"):  # type: ignore[union-attr]
            tag.decompose()
    for tag in soup.find_all(href=True):
        if tag["href"].startswith("data:"):  # type: ignore[union-attr]
            tag.decompose()

    md = markdownify.markdownify(str(soup), strip=["img"])
    return truncate_output(md, max_bytes)


def fetch_url_as_markdown(
    url: str,
    *,
    timeout: int = 15,
    user_agent: str = _USER_AGENT,
    max_bytes: int = 512_000,
    allowed_domains: list[str] | None = None,
    blocked_domains: list[str] | None = None,
) -> str:
    """Fetch a URL with SSRF protection and convert HTML to markdown.

    The body is streamed and capped at ``max_bytes`` so a malicious or oversized
    response cannot exhaust memory. When ``allowed_domains``/``blocked_domains``
    are given, the domain policy is enforced on every redirect hop. Non-HTML
    content is returned as plain text, truncated to *max_bytes*.
    """
    with httpx.Client(
        timeout=timeout,
        headers={"User-Agent": user_agent},
        follow_redirects=True,
        transport=SSRFSafeTransport(
            allowed_domains=allowed_domains, blocked_domains=blocked_domains
        ),
    ) as client:
        with client.stream("GET", url) as resp:
            resp.raise_for_status()
            content_type = resp.headers.get("content-type", "")
            text = _read_body_capped(resp, max_bytes)
    return _response_to_markdown(text, content_type, max_bytes)


async def fetch_url_as_markdown_async(
    url: str,
    *,
    timeout: int = 15,
    user_agent: str = _USER_AGENT,
    max_bytes: int = 512_000,
    allowed_domains: list[str] | None = None,
    blocked_domains: list[str] | None = None,
) -> str:
    """Async variant of ``fetch_url_as_markdown``.

    Uses ``httpx.AsyncClient`` for non-blocking I/O.
    """
    async with httpx.AsyncClient(
        timeout=timeout,
        headers={"User-Agent": user_agent},
        follow_redirects=True,
        transport=AsyncSSRFSafeTransport(
            allowed_domains=allowed_domains, blocked_domains=blocked_domains
        ),
    ) as client:
        async with client.stream("GET", url) as resp:
            resp.raise_for_status()
            content_type = resp.headers.get("content-type", "")
            text = await _read_body_capped_async(resp, max_bytes)
    return _response_to_markdown(text, content_type, max_bytes)
