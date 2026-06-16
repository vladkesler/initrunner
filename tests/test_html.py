"""Tests for initrunner._html — shared fetch + HTML->markdown utility."""

from unittest.mock import patch

import httpx
import pytest

from initrunner._html import (
    _read_body_capped,
    fetch_url_as_markdown,
    fetch_url_as_markdown_async,
)


def _patch_transport(text="", *, content_type="text/html", status_code=200, raises=None):
    """Patch the SSRF transport with an httpx.MockTransport returning a canned response.

    Drives the real ``client.stream(...) -> iter_bytes()`` path. Domain-policy
    enforcement lives in the transport itself and is covered in test_urls.py.
    """

    def handle(request: httpx.Request) -> httpx.Response:
        if raises is not None:
            raise raises
        return httpx.Response(status_code, headers={"content-type": content_type}, text=text)

    return patch(
        "initrunner._html.SSRFSafeTransport",
        lambda **kw: httpx.MockTransport(handle),
    )


def _patch_async_transport(text="", *, content_type="text/html", status_code=200, raises=None):
    def handle(request: httpx.Request) -> httpx.Response:
        if raises is not None:
            raise raises
        return httpx.Response(status_code, headers={"content-type": content_type}, text=text)

    return patch(
        "initrunner._html.AsyncSSRFSafeTransport",
        lambda **kw: httpx.MockTransport(handle),
    )


class TestFetchUrlAsMarkdown:
    def test_html_conversion(self):
        html = "<html><body><h1>Title</h1><p>Hello world</p></body></html>"

        with _patch_transport(html):
            result = fetch_url_as_markdown("https://example.com")

        assert "Title" in result
        assert "Hello world" in result

    def test_strips_script_style_noscript(self):
        html = (
            "<html><body>"
            "<script>alert(1)</script>"
            "<style>.x{color:red}</style>"
            "<noscript>Enable JS</noscript>"
            "<p>Safe content</p>"
            "</body></html>"
        )

        with _patch_transport(html):
            result = fetch_url_as_markdown("https://example.com")

        assert "alert" not in result
        assert "color:red" not in result
        assert "Enable JS" not in result
        assert "Safe content" in result

    def test_strips_base64_data_uris(self):
        html = (
            "<html><body>"
            '<img src="data:image/png;base64,abc123">'
            '<a href="data:text/html,<script>">click</a>'
            "<p>Normal</p>"
            "</body></html>"
        )

        with _patch_transport(html):
            result = fetch_url_as_markdown("https://example.com")

        assert "base64" not in result
        assert "Normal" in result

    def test_non_html_content(self):
        plain = "This is plain text content"

        with _patch_transport(plain, content_type="text/plain"):
            result = fetch_url_as_markdown("https://example.com/file.txt")

        assert result == plain

    def test_truncation(self):
        html = "<html><body><p>" + "x" * 1000 + "</p></body></html>"

        with _patch_transport(html):
            result = fetch_url_as_markdown("https://example.com", max_bytes=100)

        assert len(result) <= 100 + len("\n[truncated]")
        assert result.endswith("[truncated]")

    def test_ssrf_blocked(self):
        from initrunner.agent._urls import SSRFBlocked

        with _patch_transport(raises=SSRFBlocked("SSRF blocked: private address")):
            with pytest.raises(SSRFBlocked):
                fetch_url_as_markdown("https://internal.local")

    def test_http_error_propagates(self):
        with _patch_transport(raises=httpx.ConnectError("connection refused")):
            with pytest.raises(httpx.ConnectError):
                fetch_url_as_markdown("https://down.example.com")


class TestStreamingByteCap:
    """E3: the body is read incrementally and capped, never fully buffered."""

    class _FakeResp:
        def __init__(self, chunks, encoding="utf-8"):
            self._chunks = chunks
            self.encoding = encoding
            self.bytes_read = 0

        def iter_bytes(self):
            for c in self._chunks:
                self.bytes_read += len(c)
                yield c

    def test_read_body_capped_stops_at_ceiling(self):
        # 100 chunks x 1000 bytes = 100 KB available; cap at 2500 bytes.
        resp = self._FakeResp([b"x" * 1000 for _ in range(100)])
        text = _read_body_capped(resp, max_bytes=2500)
        # Stopped early: only a few chunks read, not the full 100 KB.
        assert resp.bytes_read <= 3000
        assert len(text) <= 3000

    def test_fetch_caps_oversized_body(self):
        # A 5 MB body must not blow past the configured max_bytes in the output.
        big = "<html><body>" + ("y" * 5_000_000) + "</body></html>"
        with _patch_transport(big):
            result = fetch_url_as_markdown("https://example.com", max_bytes=10_000)
        assert len(result) <= 10_000 + len("\n[truncated]")


# ---------------------------------------------------------------------------
# Async variant
# ---------------------------------------------------------------------------


class TestFetchUrlAsMarkdownAsync:
    @pytest.mark.anyio
    async def test_html_conversion(self):
        html = "<html><body><h1>Title</h1><p>Hello world</p></body></html>"

        with _patch_async_transport(html):
            result = await fetch_url_as_markdown_async("https://example.com")

        assert "Title" in result
        assert "Hello world" in result

    @pytest.mark.anyio
    async def test_strips_script_style_noscript(self):
        html = (
            "<html><body>"
            "<script>alert(1)</script>"
            "<style>.x{color:red}</style>"
            "<noscript>Enable JS</noscript>"
            "<p>Safe content</p>"
            "</body></html>"
        )

        with _patch_async_transport(html):
            result = await fetch_url_as_markdown_async("https://example.com")

        assert "alert" not in result
        assert "color:red" not in result
        assert "Enable JS" not in result
        assert "Safe content" in result

    @pytest.mark.anyio
    async def test_non_html_content(self):
        plain = "This is plain text content"

        with _patch_async_transport(plain, content_type="text/plain"):
            result = await fetch_url_as_markdown_async("https://example.com/file.txt")

        assert result == plain

    @pytest.mark.anyio
    async def test_truncation(self):
        html = "<html><body><p>" + "x" * 1000 + "</p></body></html>"

        with _patch_async_transport(html):
            result = await fetch_url_as_markdown_async("https://example.com", max_bytes=100)

        assert len(result) <= 100 + len("\n[truncated]")
        assert result.endswith("[truncated]")
