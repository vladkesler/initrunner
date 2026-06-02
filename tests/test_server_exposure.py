"""Fail-closed network-exposure auth for dashboard / MCP / A2A servers.

Covers the shared helpers in ``initrunner.middleware`` plus the MCP gateway's
auto-applied Bearer auth, asserting a non-loopback bind is never served
unauthenticated.
"""

from __future__ import annotations

import pytest

from initrunner.middleware import is_loopback_host, resolve_exposed_api_key


@pytest.mark.parametrize(
    "host",
    ["127.0.0.1", "localhost", "::1", "[::1]", "", "127.5.0.1"],
)
def test_is_loopback_true(host):
    assert is_loopback_host(host) is True


@pytest.mark.parametrize(
    "host",
    ["0.0.0.0", "::", "192.168.1.10", "10.0.0.5", "example.com", "0.0.0.0:8100"],
)
def test_is_loopback_false(host):
    # 0.0.0.0:8100 has a port and is not a bare IP -> treated as exposed (safe default)
    assert is_loopback_host(host) is False


def test_loopback_without_key_stays_keyless():
    effective, generated = resolve_exposed_api_key("127.0.0.1", None)
    assert effective is None
    assert generated is None


def test_loopback_honours_explicit_key():
    effective, generated = resolve_exposed_api_key("127.0.0.1", "secret")
    assert effective == "secret"
    assert generated is None


def test_exposed_with_key_is_unchanged():
    effective, generated = resolve_exposed_api_key("0.0.0.0", "secret")
    assert effective == "secret"
    assert generated is None


def test_exposed_without_key_generates_one():
    effective, generated = resolve_exposed_api_key("0.0.0.0", None)
    assert generated is not None
    assert effective == generated
    assert len(generated) >= 32  # token_urlsafe(32)


def test_mcp_gateway_applies_auth_when_exposed(monkeypatch):
    """run_mcp_gateway must set a token verifier before serving a network transport."""
    pytest.importorskip("fastmcp")
    from fastmcp import FastMCP

    from initrunner.mcp.gateway import run_mcp_gateway

    mcp = FastMCP("test")
    captured = {}

    def _fake_run(**kwargs):
        captured["auth"] = mcp.auth
        captured["kwargs"] = kwargs

    monkeypatch.setattr(mcp, "run", _fake_run)

    # Exposed host, no key -> a verifier must be installed before run.
    run_mcp_gateway(mcp, transport="streamable-http", host="0.0.0.0", port=8080)
    assert captured["auth"] is not None
    assert type(captured["auth"]).__name__ == "StaticTokenVerifier"


def test_mcp_gateway_stdio_needs_no_auth(monkeypatch):
    pytest.importorskip("fastmcp")
    from fastmcp import FastMCP

    from initrunner.mcp.gateway import run_mcp_gateway

    mcp = FastMCP("test")
    monkeypatch.setattr(mcp, "run", lambda **kw: None)
    run_mcp_gateway(mcp, transport="stdio")
    assert mcp.auth is None
