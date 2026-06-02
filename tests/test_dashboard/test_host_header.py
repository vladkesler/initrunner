"""Host-header allowlist (anti-DNS-rebinding) on the dashboard app."""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi", reason="dashboard extras not installed")

from starlette.testclient import TestClient

from initrunner.dashboard.app import create_app
from initrunner.dashboard.config import DashboardSettings


def test_rejects_unexpected_host():
    # Default (loopback) policy allows only localhost names. A rebinding page that
    # sends Host: evil.com to the local dashboard must be rejected.
    app = create_app(DashboardSettings())
    client = TestClient(app)
    resp = client.get("/api/health", headers={"host": "evil.com"})
    assert resp.status_code == 400


def test_allows_localhost_host():
    app = create_app(DashboardSettings())
    client = TestClient(app)
    resp = client.get("/api/health", headers={"host": "localhost"})
    assert resp.status_code == 200


def test_exposed_is_permissive_by_default():
    # When exposed, mandatory auth is the protection; Host is not pinned unless
    # the operator sets allowed_hosts.
    app = create_app(DashboardSettings(expose=True, api_key="k"))
    client = TestClient(app)
    resp = client.get("/api/health", headers={"host": "anything.example"})
    assert resp.status_code == 200


def test_explicit_allowed_hosts_pin():
    app = create_app(DashboardSettings(expose=True, api_key="k", allowed_hosts=["good.example"]))
    client = TestClient(app)
    assert client.get("/api/health", headers={"host": "good.example"}).status_code == 200
    assert client.get("/api/health", headers={"host": "bad.example"}).status_code == 400
