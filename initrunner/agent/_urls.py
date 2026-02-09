"""SSRF protection: URL validation and safe HTTP transport."""

from __future__ import annotations

import atexit
import ipaddress
import socket
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from urllib.parse import urlparse

import httpx

# ---------------------------------------------------------------------------
# DNS resolution timeout
# ---------------------------------------------------------------------------
_DNS_TIMEOUT: float = 10.0
_DNS_RESOLVER_POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix="ssrf_dns")
atexit.register(_DNS_RESOLVER_POOL.shutdown, wait=False)

_SockAddr = tuple[str, int] | tuple[str, int, int, int] | tuple[int, bytes]
_AddrInfo = tuple[socket.AddressFamily, socket.SocketKind, int, str, _SockAddr]


def _resolve_with_timeout(hostname: str, port: int, timeout: float) -> list[_AddrInfo]:
    """Resolve *hostname* via ``socket.getaddrinfo`` with a timeout."""
    future = _DNS_RESOLVER_POOL.submit(socket.getaddrinfo, hostname, port, proto=socket.IPPROTO_TCP)
    return future.result(timeout=timeout)


# ---------------------------------------------------------------------------
# Blocked IP ranges (RFC 1918, link-local, loopback, etc.)
# ---------------------------------------------------------------------------
_BLOCKED_NETWORKS = [
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]


class SSRFBlocked(httpx.HTTPError):
    """Raised when an SSRF attempt is detected."""


def _is_private_ip(addr: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Check whether *addr* falls in any blocked network."""
    # Unwrap IPv6-mapped IPv4 (e.g. ::ffff:127.0.0.1)
    check = addr
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
        check = addr.ipv4_mapped
    return any(check in net for net in _BLOCKED_NETWORKS)


def validate_url_ssrf(url: str, *, dns_timeout: float = _DNS_TIMEOUT) -> str | None:
    """Validate a URL against SSRF risks.

    Returns ``None`` if the URL is safe, or an error string describing the
    reason it was blocked.
    """
    try:
        parsed = urlparse(url)
    except Exception:
        return "SSRF blocked: invalid URL"

    if parsed.scheme.lower() not in ("http", "https"):
        return f"SSRF blocked: scheme '{parsed.scheme}' is not allowed"

    hostname = parsed.hostname
    if not hostname:
        return "SSRF blocked: URL has no hostname"

    port = parsed.port or (443 if parsed.scheme.lower() == "https" else 80)

    try:
        infos = _resolve_with_timeout(hostname, port, timeout=dns_timeout)
    except socket.gaierror as exc:
        return f"SSRF blocked: DNS resolution failed for '{hostname}': {exc}"
    except TimeoutError:
        return f"SSRF blocked: DNS resolution timed out for '{hostname}' after {dns_timeout}s"

    for _family, _type, _proto, _canonname, sockaddr in infos:
        ip_str = sockaddr[0]
        addr = ipaddress.ip_address(ip_str)
        if _is_private_ip(addr):
            return f"SSRF blocked: '{hostname}' resolves to private address {addr}"

    return None


class SSRFSafeTransport(httpx.HTTPTransport):
    """httpx transport that rejects requests to private/internal IPs.

    Because httpx invokes ``transport.handle_request()`` for every request
    in the redirect chain, this also blocks redirect-based SSRF.
    """

    def __init__(self, *, dns_timeout: float = _DNS_TIMEOUT, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._dns_timeout = dns_timeout

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        error = validate_url_ssrf(str(request.url), dns_timeout=self._dns_timeout)
        if error:
            raise SSRFBlocked(error)
        return super().handle_request(request)
