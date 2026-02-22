"""Cookie-based auth flow tests for the HTMX dashboard."""

from __future__ import annotations

from starlette.testclient import TestClient

from initrunner.api.app import create_dashboard_app

_TEST_KEY = "test-auth-key-5678"


def _client(api_key: str | None = _TEST_KEY) -> TestClient:
    return TestClient(create_dashboard_app(api_key=api_key))


class TestLoginFlow:
    def test_login_page_accessible(self):
        c = _client()
        resp = c.get("/login")
        assert resp.status_code == 200
        assert "API Key" in resp.text

    def test_login_correct_key_sets_cookie(self):
        c = _client()
        resp = c.post(
            "/login",
            data={"api_key": _TEST_KEY, "next": "/roles"},
            follow_redirects=False,
        )
        assert resp.status_code == 302
        cookie_header = resp.headers.get("set-cookie", "")
        assert "initrunner_token" in cookie_header
        assert "httponly" in cookie_header.lower()
        assert "samesite=strict" in cookie_header.lower()

    def test_login_wrong_key_shows_error(self):
        c = _client()
        resp = c.post(
            "/login",
            data={"api_key": "wrong-key", "next": "/roles"},
        )
        assert resp.status_code == 401
        assert "Invalid" in resp.text

    def test_login_redirects_to_next(self):
        c = _client()
        resp = c.post(
            "/login",
            data={"api_key": _TEST_KEY, "next": "/audit"},
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert resp.headers["location"] == "/audit"


class TestOpenRedirectPrevention:
    def test_absolute_url_rejected(self):
        c = _client()
        resp = c.post(
            "/login",
            data={"api_key": _TEST_KEY, "next": "https://evil.com"},
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert resp.headers["location"] == "/roles"

    def test_protocol_relative_url_rejected(self):
        c = _client()
        resp = c.post(
            "/login",
            data={"api_key": _TEST_KEY, "next": "//evil.com"},
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert resp.headers["location"] == "/roles"

    def test_javascript_scheme_rejected(self):
        c = _client()
        resp = c.post(
            "/login",
            data={"api_key": _TEST_KEY, "next": "javascript:alert(1)"},
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert resp.headers["location"] == "/roles"

    def test_safe_relative_path_allowed(self):
        c = _client()
        resp = c.post(
            "/login",
            data={"api_key": _TEST_KEY, "next": "/audit"},
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert resp.headers["location"] == "/audit"


class TestLogout:
    def test_logout_clears_cookie(self):
        c = _client()
        resp = c.get("/logout", follow_redirects=False)
        assert resp.status_code == 302
        assert "/login" in resp.headers["location"]
        cookie_header = resp.headers.get("set-cookie", "")
        assert "initrunner_token" in cookie_header


class TestCookieAuth:
    def test_cookie_grants_api_access(self):
        c = _client()
        c.cookies.set("initrunner_token", _TEST_KEY)
        resp = c.get("/api/roles")
        assert resp.status_code != 401

    def test_cookie_grants_page_access(self):
        c = _client()
        c.cookies.set("initrunner_token", _TEST_KEY)
        resp = c.get("/roles")
        assert resp.status_code == 200
        assert "InitRunner" in resp.text

    def test_invalid_cookie_rejected(self):
        c = _client()
        c.cookies.set("initrunner_token", "bad-token")
        resp = c.get("/api/roles")
        assert resp.status_code == 401

    def test_no_auth_mode_allows_all(self):
        c = _client(api_key=None)
        resp = c.get("/roles")
        assert resp.status_code == 200

    def test_query_param_sets_cookie_on_html_pages(self):
        c = _client()
        resp = c.get(f"/roles?api_key={_TEST_KEY}", follow_redirects=False)
        assert resp.status_code == 302
        assert "initrunner_token" in resp.headers.get("set-cookie", "")
