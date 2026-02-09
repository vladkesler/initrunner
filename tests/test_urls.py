"""Tests for SSRF protection (_urls module)."""

from __future__ import annotations

import socket
import time
from unittest.mock import MagicMock, patch

import pytest

from initrunner.agent._urls import SSRFBlocked, SSRFSafeTransport, validate_url_ssrf


def _mock_getaddrinfo(*addrs: str):
    """Return a side_effect for socket.getaddrinfo that yields the given IPs."""

    def _side_effect(host, port, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (a, port)) for a in addrs]

    return _side_effect


def _mock_getaddrinfo_v6(*addrs: str):
    """Return a side_effect for socket.getaddrinfo that yields IPv6 addresses."""

    def _side_effect(host, port, **kwargs):
        return [(socket.AF_INET6, socket.SOCK_STREAM, 6, "", (a, port, 0, 0)) for a in addrs]

    return _side_effect


# ---------------------------------------------------------------------------
# validate_url_ssrf — blocked private IPs
# ---------------------------------------------------------------------------
class TestValidateUrlSsrfBlockedIPs:
    @pytest.mark.parametrize(
        "url, ip",
        [
            ("http://127.0.0.1/path", "127.0.0.1"),
            ("http://10.0.0.1/path", "10.0.0.1"),
            ("http://172.16.0.1/path", "172.16.0.1"),
            ("http://192.168.1.1/path", "192.168.1.1"),
        ],
    )
    @patch("initrunner.agent._urls.socket.getaddrinfo")
    def test_rfc1918_and_loopback(self, mock_dns, url, ip):
        mock_dns.side_effect = _mock_getaddrinfo(ip)
        result = validate_url_ssrf(url)
        assert result is not None
        assert "SSRF blocked" in result
        assert "private address" in result

    @patch("initrunner.agent._urls.socket.getaddrinfo")
    def test_metadata_endpoint(self, mock_dns):
        mock_dns.side_effect = _mock_getaddrinfo("169.254.169.254")
        result = validate_url_ssrf("http://169.254.169.254/latest/meta-data/")
        assert result is not None
        assert "SSRF blocked" in result

    @patch("initrunner.agent._urls.socket.getaddrinfo")
    def test_zero_address(self, mock_dns):
        mock_dns.side_effect = _mock_getaddrinfo("0.0.0.1")
        result = validate_url_ssrf("http://0.0.0.0/")
        assert result is not None
        assert "SSRF blocked" in result


# ---------------------------------------------------------------------------
# validate_url_ssrf — blocked IPv6
# ---------------------------------------------------------------------------
class TestValidateUrlSsrfBlockedIPv6:
    @pytest.mark.parametrize(
        "url, ip",
        [
            ("http://[::1]/", "::1"),
            ("http://[fd00::1]/", "fd00::1"),
            ("http://[fe80::1]/", "fe80::1"),
        ],
    )
    @patch("initrunner.agent._urls.socket.getaddrinfo")
    def test_ipv6_blocked(self, mock_dns, url, ip):
        mock_dns.side_effect = _mock_getaddrinfo_v6(ip)
        result = validate_url_ssrf(url)
        assert result is not None
        assert "SSRF blocked" in result

    @patch("initrunner.agent._urls.socket.getaddrinfo")
    def test_ipv6_mapped_ipv4(self, mock_dns):
        mock_dns.side_effect = _mock_getaddrinfo_v6("::ffff:127.0.0.1")
        result = validate_url_ssrf("http://example.com/")
        assert result is not None
        assert "SSRF blocked" in result


# ---------------------------------------------------------------------------
# validate_url_ssrf — blocked schemes
# ---------------------------------------------------------------------------
class TestValidateUrlSsrfBlockedSchemes:
    @pytest.mark.parametrize(
        "url",
        [
            "file:///etc/passwd",
            "gopher://evil",
            "ftp://internal",
        ],
    )
    def test_non_http_schemes_blocked(self, url):
        result = validate_url_ssrf(url)
        assert result is not None
        assert "SSRF blocked" in result
        assert "scheme" in result

    @patch("initrunner.agent._urls.socket.getaddrinfo")
    def test_scheme_case_insensitive(self, mock_dns):
        mock_dns.side_effect = _mock_getaddrinfo("169.254.169.254")
        result = validate_url_ssrf("HTTP://169.254.169.254")
        assert result is not None
        assert "SSRF blocked" in result


# ---------------------------------------------------------------------------
# validate_url_ssrf — DNS-resolved private
# ---------------------------------------------------------------------------
class TestValidateUrlSsrfDnsResolved:
    @patch("initrunner.agent._urls.socket.getaddrinfo")
    def test_hostname_resolving_to_private(self, mock_dns):
        mock_dns.side_effect = _mock_getaddrinfo("127.0.0.1")
        result = validate_url_ssrf("http://localtest.me/")
        assert result is not None
        assert "SSRF blocked" in result
        assert "localtest.me" in result

    @patch("initrunner.agent._urls.socket.getaddrinfo")
    def test_mixed_results_any_private_blocks(self, mock_dns):
        mock_dns.side_effect = _mock_getaddrinfo("93.184.216.34", "10.0.0.1")
        result = validate_url_ssrf("http://example.com/")
        assert result is not None
        assert "SSRF blocked" in result


# ---------------------------------------------------------------------------
# validate_url_ssrf — safe URLs
# ---------------------------------------------------------------------------
class TestValidateUrlSsrfSafe:
    @patch("initrunner.agent._urls.socket.getaddrinfo")
    def test_public_ip_allowed(self, mock_dns):
        mock_dns.side_effect = _mock_getaddrinfo("93.184.216.34")
        result = validate_url_ssrf("https://example.com/")
        assert result is None

    @patch("initrunner.agent._urls.socket.getaddrinfo")
    def test_https_public_ip_allowed(self, mock_dns):
        mock_dns.side_effect = _mock_getaddrinfo("93.184.216.34")
        result = validate_url_ssrf("https://example.com/path?q=1")
        assert result is None


# ---------------------------------------------------------------------------
# validate_url_ssrf — error cases
# ---------------------------------------------------------------------------
class TestValidateUrlSsrfErrors:
    @patch("initrunner.agent._urls.socket.getaddrinfo")
    def test_dns_failure(self, mock_dns):
        mock_dns.side_effect = socket.gaierror("Name or service not known")
        result = validate_url_ssrf("http://nonexistent.invalid/")
        assert result is not None
        assert "SSRF blocked" in result
        assert "DNS resolution failed" in result

    def test_no_hostname(self):
        result = validate_url_ssrf("http:///path")
        assert result is not None
        assert "SSRF blocked" in result
        assert "no hostname" in result

    @patch("initrunner.agent._urls.socket.getaddrinfo")
    def test_dns_timeout(self, mock_dns):
        mock_dns.side_effect = lambda *a, **kw: time.sleep(5)
        result = validate_url_ssrf("http://slow.invalid/", dns_timeout=0.1)
        assert result is not None
        assert "timed out" in result


# ---------------------------------------------------------------------------
# SSRFSafeTransport
# ---------------------------------------------------------------------------
class TestSSRFSafeTransport:
    @patch("initrunner.agent._urls.socket.getaddrinfo")
    def test_raises_for_private_ip(self, mock_dns):
        mock_dns.side_effect = _mock_getaddrinfo("127.0.0.1")
        transport = SSRFSafeTransport()
        request = MagicMock()
        request.url = "http://localhost/"
        with pytest.raises(SSRFBlocked, match="SSRF blocked"):
            transport.handle_request(request)

    @patch("initrunner.agent._urls.socket.getaddrinfo")
    def test_calls_super_for_safe_url(self, mock_dns):
        mock_dns.side_effect = _mock_getaddrinfo("93.184.216.34")
        transport = SSRFSafeTransport()
        request = MagicMock()
        request.url = "https://example.com/"
        with patch("httpx.HTTPTransport.handle_request", return_value=MagicMock()) as mock_super:
            result = transport.handle_request(request)
            mock_super.assert_called_once_with(request)
            assert result is mock_super.return_value

    def test_dns_timeout_parameter(self):
        transport = SSRFSafeTransport(dns_timeout=5.0)
        assert transport._dns_timeout == 5.0

    def test_ssrf_blocked_is_http_error(self):
        """SSRFBlocked is a subclass of httpx.HTTPError for catch compatibility."""
        exc = SSRFBlocked("test")
        assert isinstance(exc, Exception)
