"""Tests for SSRF protection (_urls module)."""

from __future__ import annotations

import socket
import time
from unittest.mock import MagicMock, patch

import httpx
import pytest

from initrunner.agent._urls import (
    SSRFBlocked,
    SSRFSafeTransport,
    _resolve_safe_ip,
    validate_url_ssrf,
)


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
        with pytest.raises(SSRFBlocked, match="SSRF blocked"):
            transport.handle_request(httpx.Request("GET", "http://localhost/"))

    @patch("initrunner.agent._urls.socket.getaddrinfo")
    def test_pins_validated_ip_for_safe_url(self, mock_dns):
        # The connection must target the SAME IP we validated (no re-resolution),
        # with Host + TLS SNI preserved -- this is what closes the rebinding TOCTOU.
        mock_dns.side_effect = _mock_getaddrinfo("93.184.216.34")
        transport = SSRFSafeTransport()
        request = httpx.Request("GET", "https://example.com/path")
        with patch("httpx.HTTPTransport.handle_request", return_value=MagicMock()) as mock_super:
            result = transport.handle_request(request)
            mock_super.assert_called_once()
            passed = mock_super.call_args.args[0]
            assert passed.url.host == "93.184.216.34"  # pinned to the validated IP
            assert passed.extensions.get("sni_hostname") == "example.com"
            assert passed.headers["host"] == "example.com"  # original Host preserved
            assert result is mock_super.return_value

    @patch("initrunner.agent._urls.socket.getaddrinfo")
    def test_blocks_non_http_scheme(self, mock_dns):
        transport = SSRFSafeTransport()
        with pytest.raises(SSRFBlocked, match="scheme"):
            transport.handle_request(httpx.Request("GET", "file://etc/passwd"))
        mock_dns.assert_not_called()

    def test_dns_timeout_parameter(self):
        transport = SSRFSafeTransport(dns_timeout=5.0)
        assert transport._dns_timeout == 5.0

    def test_ssrf_blocked_is_http_error(self):
        """SSRFBlocked is a subclass of httpx.HTTPError for catch compatibility."""
        exc = SSRFBlocked("test")
        assert isinstance(exc, Exception)


# ---------------------------------------------------------------------------
# Newly-blocked CIDR ranges (CGNAT, TEST-NET, benchmarking, reserved, IPv6 doc)
# ---------------------------------------------------------------------------
class TestExpandedBlocklist:
    @pytest.mark.parametrize(
        "ip",
        [
            "100.64.0.1",  # CGNAT
            "100.100.100.200",  # Alibaba metadata (inside CGNAT)
            "192.0.0.1",  # IETF protocol assignments
            "192.0.2.5",  # TEST-NET-1
            "198.18.0.1",  # benchmarking
            "198.51.100.7",  # TEST-NET-2
            "203.0.113.9",  # TEST-NET-3
            "240.0.0.1",  # reserved
            "255.255.255.255",  # broadcast (inside 240/4)
        ],
    )
    @patch("initrunner.agent._urls.socket.getaddrinfo")
    def test_ipv4_ranges_blocked(self, mock_dns, ip):
        mock_dns.side_effect = _mock_getaddrinfo(ip)
        assert validate_url_ssrf("http://host.example/") is not None

    @patch("initrunner.agent._urls.socket.getaddrinfo")
    def test_ipv6_doc_and_unspecified_blocked(self, mock_dns):
        for ip in ("2001:db8::1", "::"):
            mock_dns.side_effect = _mock_getaddrinfo_v6(ip)
            assert validate_url_ssrf("http://host.example/") is not None


# ---------------------------------------------------------------------------
# IP pinning helper + DNS-rebinding defence
# ---------------------------------------------------------------------------
class TestResolveSafeIp:
    def test_public_ip_literal_returned(self):
        assert _resolve_safe_ip("93.184.216.34", 443, 10.0) == "93.184.216.34"

    def test_private_ip_literal_raises(self):
        with pytest.raises(SSRFBlocked):
            _resolve_safe_ip("169.254.169.254", 80, 10.0)

    @patch("initrunner.agent._urls.socket.getaddrinfo")
    def test_mixed_resolution_blocks(self, mock_dns):
        # public + private together -> never connect (the rebinding multiplexing case)
        mock_dns.side_effect = _mock_getaddrinfo("93.184.216.34", "127.0.0.1")
        with pytest.raises(SSRFBlocked):
            _resolve_safe_ip("rebind.example", 80, 10.0)

    @patch("initrunner.agent._urls.socket.getaddrinfo")
    def test_picks_first_public_ip(self, mock_dns):
        mock_dns.side_effect = _mock_getaddrinfo("93.184.216.34", "93.184.216.35")
        assert _resolve_safe_ip("ok.example", 80, 10.0) == "93.184.216.34"


# ---------------------------------------------------------------------------
# Cloud metadata endpoints, IPv6 transition forms, multicast, trailing dot
# ---------------------------------------------------------------------------
class TestCloudMetadataAndTransitionForms:
    @pytest.mark.parametrize(
        "ip",
        [
            "168.63.129.16",  # Azure WireServer (PUBLIC IP -- only the metadata guard catches it)
            "169.254.169.254",  # AWS/GCP/Azure IMDS
            "169.254.170.2",  # AWS ECS task role credentials
            "100.100.100.200",  # Alibaba
            "192.0.0.192",  # Oracle Cloud Classic
        ],
    )
    def test_cloud_metadata_ipv4_blocked(self, ip):
        import ipaddress

        from initrunner.agent._urls import _is_private_ip

        assert _is_private_ip(ipaddress.ip_address(ip)) is True

    def test_azure_metadata_is_public_ip_not_in_ranges(self):
        """168.63.129.16 must be caught by the metadata guard, not a CIDR range."""
        import ipaddress

        from initrunner.agent._urls import _BLOCKED_NETWORKS, _is_private_ip

        addr = ipaddress.ip_address("168.63.129.16")
        assert not any(addr in net for net in _BLOCKED_NETWORKS)  # public IP
        assert _is_private_ip(addr) is True  # but still blocked

    @pytest.mark.parametrize(
        "ipv6",
        [
            "2002:7f00:1::",  # 6to4 encoding 127.0.0.1
            "2002:a00:1::",  # 6to4 encoding 10.0.0.1
            "64:ff9b::7f00:1",  # NAT64 well-known prefix encoding 127.0.0.1
            "::ffff:169.254.169.254",  # IPv4-mapped metadata
            "::7f00:1",  # IPv4-compatible (deprecated) encoding 127.0.0.1
        ],
    )
    def test_ipv6_embedded_private_ipv4_blocked(self, ipv6):
        import ipaddress

        from initrunner.agent._urls import _is_private_ip

        assert _is_private_ip(ipaddress.ip_address(ipv6)) is True

    def test_ipv6_embedded_metadata_blocked(self):
        """6to4-wrapped Azure metadata is caught by the exhaustive metadata decode."""
        import ipaddress

        from initrunner.agent._urls import _is_private_ip

        # 6to4 wrapper around 168.63.129.16 (a8 3f 81 10)
        assert _is_private_ip(ipaddress.ip_address("2002:a83f:8110::")) is True

    @pytest.mark.parametrize("ip", ["224.0.0.1", "239.255.255.250"])
    def test_ipv4_multicast_blocked(self, ip):
        import ipaddress

        from initrunner.agent._urls import _is_private_ip

        assert _is_private_ip(ipaddress.ip_address(ip)) is True

    def test_public_ipv6_not_blocked(self):
        """A genuine public IPv6 must not be misclassified."""
        import ipaddress

        from initrunner.agent._urls import _is_private_ip

        assert _is_private_ip(ipaddress.ip_address("2606:4700:4700::1111")) is False  # Cloudflare

    def test_trailing_dot_does_not_bypass_blocklist(self):
        from initrunner.agent._urls import check_domain_filter

        # blocked.com. (trailing dot) must still match the blocklist for blocked.com
        result = check_domain_filter(
            "https://blocked.com./path", allowed_domains=[], blocked_domains=["blocked.com"]
        )
        assert result is not None and "blocked" in result

    @patch("initrunner.agent._urls.socket.getaddrinfo")
    def test_trailing_dot_metadata_host_blocked(self, mock_dns):
        mock_dns.side_effect = _mock_getaddrinfo("169.254.169.254")
        with pytest.raises(SSRFBlocked):
            _resolve_safe_ip("metadata.internal.", 80, 10.0)
