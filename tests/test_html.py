"""Tests for initrunner._html — shared fetch + HTML→markdown utility."""

from unittest.mock import MagicMock, patch

import httpx
import pytest

from initrunner._html import fetch_url_as_markdown


def _mock_response(text: str, content_type: str = "text/html", status_code: int = 200):
    """Build a fake httpx.Response."""
    return httpx.Response(
        status_code=status_code,
        text=text,
        headers={"content-type": content_type},
        request=httpx.Request("GET", "https://example.com"),
    )


def _patch_client(response=None, side_effect=None):
    """Create a mock httpx.Client context manager that returns the given response."""
    mock_cm = MagicMock()
    mock_cm.__enter__ = MagicMock(return_value=mock_cm)
    mock_cm.__exit__ = MagicMock(return_value=False)
    if side_effect:
        mock_cm.get.side_effect = side_effect
    else:
        mock_cm.get.return_value = response
    return patch("initrunner._html.httpx.Client", return_value=mock_cm)


class TestFetchUrlAsMarkdown:
    def test_html_conversion(self):
        html = "<html><body><h1>Title</h1><p>Hello world</p></body></html>"

        with _patch_client(_mock_response(html)):
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

        with _patch_client(_mock_response(html)):
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

        with _patch_client(_mock_response(html)):
            result = fetch_url_as_markdown("https://example.com")

        assert "base64" not in result
        assert "Normal" in result

    def test_non_html_content(self):
        plain = "This is plain text content"

        with _patch_client(_mock_response(plain, content_type="text/plain")):
            result = fetch_url_as_markdown("https://example.com/file.txt")

        assert result == plain

    def test_truncation(self):
        html = "<html><body><p>" + "x" * 1000 + "</p></body></html>"

        with _patch_client(_mock_response(html)):
            result = fetch_url_as_markdown("https://example.com", max_bytes=100)

        assert len(result) <= 100 + len("\n[truncated]")
        assert result.endswith("[truncated]")

    def test_ssrf_blocked(self):
        from initrunner.agent._urls import SSRFBlocked

        with _patch_client(side_effect=SSRFBlocked("SSRF blocked: private address")):
            with pytest.raises(SSRFBlocked):
                fetch_url_as_markdown("https://internal.local")

    def test_http_error_propagates(self):
        with _patch_client(side_effect=httpx.ConnectError("connection refused")):
            with pytest.raises(httpx.ConnectError):
                fetch_url_as_markdown("https://down.example.com")
