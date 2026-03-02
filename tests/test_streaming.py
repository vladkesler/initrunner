"""Tests for initrunner.api._streaming: upload staging and attachment resolution."""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from initrunner.api._streaming import resolve_attachments


@pytest.fixture
def event_loop():
    """Create an event loop for async tests."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


def _run(coro):
    """Run an async coroutine synchronously."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# Attachment URL scheme validation
# ---------------------------------------------------------------------------


class TestAttachmentUrlValidation:
    def test_http_url_accepted(self):
        attachments, _ = _run(resolve_attachments(None, "http://example.com/image.png"))
        assert "http://example.com/image.png" in attachments

    def test_https_url_accepted(self):
        with patch("initrunner.api._streaming.validate_url_ssrf", return_value=None):
            attachments, _ = _run(resolve_attachments(None, "https://example.com/image.png"))
            assert "https://example.com/image.png" in attachments

    def test_file_scheme_rejected(self):
        attachments, _ = _run(resolve_attachments(None, "file:///etc/passwd"))
        assert len(attachments) == 0

    def test_javascript_scheme_rejected(self):
        attachments, _ = _run(resolve_attachments(None, "javascript:alert(1)"))
        assert len(attachments) == 0

    def test_data_scheme_rejected(self):
        attachments, _ = _run(resolve_attachments(None, "data:text/html,<script>alert(1)</script>"))
        assert len(attachments) == 0

    def test_ftp_scheme_rejected(self):
        attachments, _ = _run(resolve_attachments(None, "ftp://evil.com/file"))
        assert len(attachments) == 0

    def test_no_scheme_rejected(self):
        attachments, _ = _run(resolve_attachments(None, "/etc/passwd"))
        assert len(attachments) == 0

    def test_mixed_valid_and_invalid(self):
        with patch("initrunner.api._streaming.validate_url_ssrf", return_value=None):
            urls = "https://example.com/ok.png, file:///etc/passwd, javascript:alert(1)"
            attachments, _ = _run(resolve_attachments(None, urls))
            assert len(attachments) == 1
            assert "https://example.com/ok.png" in attachments

    def test_empty_urls_ignored(self):
        attachments, _ = _run(resolve_attachments(None, ""))
        assert len(attachments) == 0

    def test_none_urls_ignored(self):
        attachments, _ = _run(resolve_attachments(None, None))
        assert len(attachments) == 0


# ---------------------------------------------------------------------------
# SSRF blocking
# ---------------------------------------------------------------------------


class TestAttachmentSsrfBlocking:
    def test_private_ip_blocked(self):
        with patch(
            "initrunner.api._streaming.validate_url_ssrf",
            return_value="SSRF blocked: resolves to private address",
        ):
            attachments, _ = _run(resolve_attachments(None, "http://192.168.1.1/internal"))
            assert len(attachments) == 0

    def test_loopback_blocked(self):
        with patch(
            "initrunner.api._streaming.validate_url_ssrf",
            return_value="SSRF blocked: resolves to private address 127.0.0.1",
        ):
            attachments, _ = _run(resolve_attachments(None, "http://127.0.0.1/secret"))
            assert len(attachments) == 0

    def test_public_url_allowed(self):
        with patch("initrunner.api._streaming.validate_url_ssrf", return_value=None):
            attachments, _ = _run(resolve_attachments(None, "https://cdn.example.com/image.png"))
            assert len(attachments) == 1
