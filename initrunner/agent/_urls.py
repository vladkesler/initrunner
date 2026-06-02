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
    ipaddress.ip_network("0.0.0.0/8"),  # "this" network (incl. 0.0.0.0)
    ipaddress.ip_network("127.0.0.0/8"),  # loopback
    ipaddress.ip_network("10.0.0.0/8"),  # RFC 1918
    ipaddress.ip_network("172.16.0.0/12"),  # RFC 1918
    ipaddress.ip_network("192.168.0.0/16"),  # RFC 1918
    ipaddress.ip_network("169.254.0.0/16"),  # link-local (incl. 169.254.169.254 metadata)
    ipaddress.ip_network("100.64.0.0/10"),  # RFC 6598 CGNAT (Alibaba metadata 100.100.100.200)
    ipaddress.ip_network("192.0.0.0/24"),  # RFC 6890 IETF protocol assignments
    ipaddress.ip_network("192.0.2.0/24"),  # TEST-NET-1
    ipaddress.ip_network("198.18.0.0/15"),  # RFC 2544 benchmarking
    ipaddress.ip_network("198.51.100.0/24"),  # TEST-NET-2
    ipaddress.ip_network("203.0.113.0/24"),  # TEST-NET-3
    ipaddress.ip_network("240.0.0.0/4"),  # reserved/future (incl. 255.255.255.255 broadcast)
    ipaddress.ip_network("::1/128"),  # IPv6 loopback
    ipaddress.ip_network("::/128"),  # IPv6 unspecified
    ipaddress.ip_network("fc00::/7"),  # IPv6 unique-local
    ipaddress.ip_network("fe80::/10"),  # IPv6 link-local
    ipaddress.ip_network("2001:db8::/32"),  # IPv6 documentation
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


def check_domain_filter(
    url: str,
    allowed_domains: list[str],
    blocked_domains: list[str],
) -> str | None:
    """Validate URL against domain allow/block lists.

    Returns None if allowed, or an error string if blocked/invalid.
    """
    try:
        parsed = urlparse(url)
        hostname = parsed.hostname or ""
    except Exception:
        return "Error: invalid URL"

    if allowed_domains:
        if hostname not in allowed_domains:
            return f"Error: domain '{hostname}' is not in the allowed domains list"
    elif blocked_domains:
        if hostname in blocked_domains:
            return f"Error: domain '{hostname}' is blocked"
    return None


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


def _resolve_safe_ip(host: str, port: int, dns_timeout: float) -> str:
    """Resolve *host* and return a single validated public IP to connect to.

    Raises :class:`SSRFBlocked` if the host is missing, fails to resolve, or any
    resolved address is private/internal. Returning a concrete IP lets the caller
    pin the connection to it, so a rebinding resolver cannot swap in a private
    address between validation and connect (the DNS-rebinding TOCTOU).
    """
    if not host:
        raise SSRFBlocked("SSRF blocked: URL has no hostname")

    # Bracketed IPv6 literal -> strip brackets for ip_address().
    bare = host[1:-1] if host.startswith("[") and host.endswith("]") else host

    try:
        literal = ipaddress.ip_address(bare)
    except ValueError:
        literal = None

    if literal is not None:
        if _is_private_ip(literal):
            raise SSRFBlocked(f"SSRF blocked: '{host}' is a private address {literal}")
        return bare

    try:
        infos = _resolve_with_timeout(bare, port, timeout=dns_timeout)
    except socket.gaierror as exc:
        raise SSRFBlocked(f"SSRF blocked: DNS resolution failed for '{host}': {exc}") from exc
    except TimeoutError as exc:
        raise SSRFBlocked(
            f"SSRF blocked: DNS resolution timed out for '{host}' after {dns_timeout}s"
        ) from exc

    pinned: str | None = None
    for _family, _type, _proto, _canonname, sockaddr in infos:
        ip_str = str(sockaddr[0])
        addr = ipaddress.ip_address(ip_str)
        # Block if ANY resolved address is private -- never connect when the host
        # multiplexes public and internal addresses.
        if _is_private_ip(addr):
            raise SSRFBlocked(f"SSRF blocked: '{host}' resolves to private address {addr}")
        if pinned is None:
            pinned = ip_str

    if pinned is None:
        raise SSRFBlocked(f"SSRF blocked: '{host}' did not resolve to any address")
    return pinned


def _pin_request(request: httpx.Request, dns_timeout: float) -> None:
    """Rewrite *request* in place to connect to a validated, pinned IP.

    Validates the scheme, resolves+checks the host once, then points the URL at
    the resolved IP while preserving the original ``Host`` header and setting the
    TLS ``sni_hostname`` so certificate verification still targets the hostname.
    httpx therefore connects to the exact IP we validated -- it does not
    re-resolve -- which closes the DNS-rebinding window. Runs per redirect hop.
    """
    url = request.url
    scheme = url.scheme.lower()
    if scheme not in ("http", "https"):
        raise SSRFBlocked(f"SSRF blocked: scheme '{url.scheme}' is not allowed")

    host = url.host
    port = url.port or (443 if scheme == "https" else 80)
    pinned_ip = _resolve_safe_ip(host, port, dns_timeout)

    if pinned_ip == host:
        return  # already an IP literal; nothing to rewrite

    # Preserve the Host header (httpx set it to the original host[:port]) and the
    # TLS SNI/cert hostname, then repoint the connection at the pinned IP.
    request.headers.setdefault("host", url.netloc.decode("ascii"))
    request.extensions = {**request.extensions, "sni_hostname": host}
    request.url = url.copy_with(host=pinned_ip)


class SSRFSafeTransport(httpx.HTTPTransport):
    """httpx transport that rejects requests to private/internal IPs.

    Validation pins the resolved IP for the actual connection, so a rebinding
    resolver cannot swap in a private address after the check. httpx invokes
    ``handle_request()`` for every redirect hop, so this also blocks
    redirect-based SSRF.
    """

    def __init__(self, *, dns_timeout: float = _DNS_TIMEOUT, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._dns_timeout = dns_timeout

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        _pin_request(request, self._dns_timeout)
        return super().handle_request(request)


class AsyncSSRFSafeTransport(httpx.AsyncHTTPTransport):
    """Async httpx transport that rejects requests to private/internal IPs."""

    def __init__(self, *, dns_timeout: float = _DNS_TIMEOUT, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._dns_timeout = dns_timeout

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        _pin_request(request, self._dns_timeout)
        return await super().handle_async_request(request)
