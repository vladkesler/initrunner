"""Tests for optional dashboard authentication."""

import pytest
from starlette.testclient import TestClient

from initrunner.dashboard.app import create_app
from initrunner.dashboard.config import DashboardSettings

API_KEY = "test-secret-key-1234"


@pytest.fixture
def auth_app():
    """Dashboard app with authentication enabled."""
    settings = DashboardSettings(api_key=API_KEY)
    return create_app(settings)


@pytest.fixture
def auth_client(auth_app):
    return TestClient(auth_app, raise_server_exceptions=False)


@pytest.fixture
def noauth_app():
    """Dashboard app without authentication (default)."""
    settings = DashboardSettings()
    return create_app(settings)


@pytest.fixture
def noauth_client(noauth_app):
    return TestClient(noauth_app, raise_server_exceptions=False)


# -- No-auth mode: backward compatible ------------------------------------


class TestNoAuth:
    def test_health_accessible(self, noauth_client):
        resp = noauth_client.get("/api/health")
        assert resp.status_code == 200

    def test_api_routes_accessible(self, noauth_client):
        resp = noauth_client.get("/api/agents")
        assert resp.status_code == 200

    def test_no_login_route(self, noauth_client):
        resp = noauth_client.get("/login")
        # Without auth, /login is not registered -- falls through to SPA or 404
        assert resp.status_code in (404, 200)


# -- Auth mode: enforcement ------------------------------------------------


class TestAuthEnforcement:
    def test_health_stays_public(self, auth_client):
        resp = auth_client.get("/api/health")
        assert resp.status_code == 200

    def test_api_route_returns_401_json(self, auth_client):
        resp = auth_client.get("/api/agents", headers={"Accept": "application/json"})
        assert resp.status_code == 401
        assert resp.json()["detail"] == "Invalid API key"

    def test_html_request_redirects_to_login(self, auth_client):
        resp = auth_client.get("/", headers={"Accept": "text/html"}, follow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers["location"].startswith("/login")

    def test_deep_link_preserved_in_redirect(self, auth_client):
        resp = auth_client.get(
            "/agents/abc123", headers={"Accept": "text/html"}, follow_redirects=False
        )
        assert resp.status_code == 302
        assert "/login?next=" in resp.headers["location"]
        assert "agents" in resp.headers["location"]

    def test_docs_protected(self, auth_client):
        resp = auth_client.get("/api/docs", headers={"Accept": "application/json"})
        assert resp.status_code == 401

    def test_openapi_protected(self, auth_client):
        resp = auth_client.get("/api/openapi.json")
        assert resp.status_code == 401


# -- Auth mode: Bearer token -----------------------------------------------


class TestBearerAuth:
    def test_valid_bearer_succeeds(self, auth_client):
        resp = auth_client.get("/api/agents", headers={"Authorization": f"Bearer {API_KEY}"})
        assert resp.status_code == 200

    def test_invalid_bearer_rejected(self, auth_client):
        resp = auth_client.get("/api/agents", headers={"Authorization": "Bearer wrong-key"})
        assert resp.status_code == 401


# -- Auth mode: login flow -------------------------------------------------


class TestLoginFlow:
    def test_login_page_accessible(self, auth_client):
        resp = auth_client.get("/login")
        assert resp.status_code == 200
        assert "InitRunner" in resp.text
        assert 'type="password"' in resp.text

    def test_login_page_preserves_next(self, auth_client):
        resp = auth_client.get("/login?next=/agents/abc")
        assert resp.status_code == 200
        assert "/agents/abc" in resp.text

    def test_login_rejects_bad_key(self, auth_client):
        resp = auth_client.post(
            "/login",
            data={"api_key": "wrong", "next": "/"},
            follow_redirects=False,
        )
        assert resp.status_code == 401
        assert "Invalid API key" in resp.text

    def test_login_sets_cookie_and_redirects(self, auth_client):
        resp = auth_client.post(
            "/login",
            data={"api_key": API_KEY, "next": "/agents"},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert resp.headers["location"] == "/agents"
        assert "initrunner_token" in resp.headers.get("set-cookie", "")

    def test_cookie_authenticates_subsequent_requests(self, auth_client):
        # Log in to get the cookie
        login_resp = auth_client.post(
            "/login",
            data={"api_key": API_KEY, "next": "/"},
            follow_redirects=False,
        )
        assert login_resp.status_code == 303

        # The TestClient carries cookies forward
        resp = auth_client.get("/api/agents")
        assert resp.status_code == 200


# -- Auth mode: logout -----------------------------------------------------


class TestLogout:
    def test_logout_clears_cookie(self, auth_client):
        # Log in first
        auth_client.post(
            "/login",
            data={"api_key": API_KEY, "next": "/"},
            follow_redirects=False,
        )

        # Verify access works
        assert auth_client.get("/api/agents").status_code == 200

        # Log out
        resp = auth_client.post("/logout", follow_redirects=False)
        assert resp.status_code == 303
        assert resp.headers["location"] == "/login"

        # Subsequent requests fail (cookie cleared)
        resp = auth_client.get("/api/agents", headers={"Accept": "application/json"})
        assert resp.status_code == 401


# -- Open redirect prevention ----------------------------------------------


class TestOpenRedirect:
    def test_absolute_url_rejected(self, auth_client):
        resp = auth_client.post(
            "/login",
            data={"api_key": API_KEY, "next": "https://evil.com/steal"},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert resp.headers["location"] == "/"

    def test_protocol_relative_rejected(self, auth_client):
        resp = auth_client.post(
            "/login",
            data={"api_key": API_KEY, "next": "//evil.com"},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert resp.headers["location"] == "/"

    def test_relative_path_allowed(self, auth_client):
        resp = auth_client.post(
            "/login",
            data={"api_key": API_KEY, "next": "/compose/abc"},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert resp.headers["location"] == "/compose/abc"
