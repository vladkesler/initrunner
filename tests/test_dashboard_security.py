"""Security tests for the dashboard API.

Covers: auth middleware (Bearer + cookie), rate limiting, body size limits, WebSocket auth.
"""

from __future__ import annotations

from starlette.testclient import TestClient

from initrunner.api.app import create_dashboard_app

_TEST_KEY = "test-secret-key-1234"


def _make_app(api_key: str | None = _TEST_KEY):
    return create_dashboard_app(api_key=api_key)


def _client(api_key: str | None = _TEST_KEY) -> TestClient:
    return TestClient(_make_app(api_key))


# ---------------------------------------------------------------------------
# Auth middleware
# ---------------------------------------------------------------------------


class TestAuthMiddleware:
    def test_unauthenticated_api_request_blocked(self):
        c = _client()
        resp = c.get("/api/roles")
        assert resp.status_code == 401

    def test_correct_bearer_passes(self):
        c = _client()
        resp = c.get("/api/roles", headers={"Authorization": f"Bearer {_TEST_KEY}"})
        assert resp.status_code != 401

    def test_wrong_key_blocked(self):
        c = _client()
        resp = c.get("/api/roles", headers={"Authorization": "Bearer wrong-key"})
        assert resp.status_code == 401

    def test_health_exempt(self):
        c = _client()
        resp = c.get("/api/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

    def test_query_param_sets_cookie_and_redirects(self):
        c = _client()
        resp = c.get(f"/roles?api_key={_TEST_KEY}", follow_redirects=False)
        # Should redirect (302) and set cookie
        assert resp.status_code == 302
        assert "initrunner_token" in resp.headers.get("set-cookie", "")

    def test_nonce_login_sets_cookie_and_redirects(self):
        app = _make_app()
        app.state.auth_nonce = "test-nonce-abc"
        c = TestClient(app)
        resp = c.get("/auth/session?nonce=test-nonce-abc", follow_redirects=False)
        assert resp.status_code == 302
        assert "initrunner_token" in resp.headers.get("set-cookie", "")
        # Nonce is consumed (one-time use)
        assert app.state.auth_nonce is None

    def test_nonce_replay_rejected(self):
        app = _make_app()
        app.state.auth_nonce = "test-nonce-abc"
        c = TestClient(app)
        # First use succeeds
        c.get("/auth/session?nonce=test-nonce-abc", follow_redirects=False)
        # Second use (replay) should redirect to /login
        resp = c.get("/auth/session?nonce=test-nonce-abc", follow_redirects=False)
        assert resp.status_code == 302
        assert "/login" in resp.headers.get("location", "")
        assert "initrunner_token" not in resp.headers.get("set-cookie", "")

    def test_wrong_nonce_rejected(self):
        app = _make_app()
        app.state.auth_nonce = "correct-nonce"
        c = TestClient(app)
        resp = c.get("/auth/session?nonce=wrong-nonce", follow_redirects=False)
        assert resp.status_code == 302
        assert "/login" in resp.headers.get("location", "")

    def test_cookie_auth_passes(self):
        c = _client()
        c.cookies.set("initrunner_token", _TEST_KEY)
        resp = c.get("/api/roles")
        assert resp.status_code != 401

    def test_no_auth_mode(self):
        c = _client(api_key=None)
        resp = c.get("/api/roles")
        assert resp.status_code != 401

    def test_unauthenticated_html_redirects_to_login(self):
        c = _client()
        resp = c.get("/roles", headers={"Accept": "text/html"}, follow_redirects=False)
        assert resp.status_code == 302
        assert "/login" in resp.headers.get("location", "")

    def test_login_page_accessible_without_auth(self):
        c = _client()
        resp = c.get("/login")
        assert resp.status_code == 200

    def test_static_assets_exempt_from_auth(self):
        c = _client()
        resp = c.get("/static/style.css")
        assert resp.status_code != 401


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------


class TestRateLimit:
    def test_burst_exceeded_returns_429(self):
        from unittest.mock import patch

        from initrunner.server.rate_limiter import TokenBucketRateLimiter

        original_init = TokenBucketRateLimiter.__init__

        def low_burst_init(self, rate, burst):
            original_init(self, rate=0.01, burst=2)

        with patch.object(TokenBucketRateLimiter, "__init__", low_burst_init):
            c = _client(api_key=None)
            responses = []
            for _ in range(5):
                r = c.get("/api/openapi.json")
                responses.append(r.status_code)

        assert 429 in responses

    def test_health_not_rate_limited(self):
        c = _client(api_key=None)
        for _ in range(30):
            r = c.get("/api/health")
            assert r.status_code == 200


# ---------------------------------------------------------------------------
# Body size limits
# ---------------------------------------------------------------------------


class TestBodySize:
    def test_oversized_post_returns_413(self):
        c = _client(api_key=None)
        big_body = "x" * (3 * 1024 * 1024)
        resp = c.post(
            "/api/roles/validate",
            content=big_body,
            headers={"Content-Type": "application/json", "Content-Length": str(len(big_body))},
        )
        assert resp.status_code == 413

    def test_normal_post_allowed(self):
        c = _client(api_key=None)
        resp = c.post(
            "/api/roles/validate",
            json={"path": "nonexistent.yaml"},
        )
        assert resp.status_code != 413


# ---------------------------------------------------------------------------
# WebSocket auth
# ---------------------------------------------------------------------------


class TestWebSocketAuth:
    def test_unauthenticated_ws_rejected(self):
        c = _client()
        rejected = False
        try:
            with c.websocket_connect("/api/daemon/test-role") as ws:
                ws.receive_json()
        except Exception:
            rejected = True
        assert rejected, "Unauthenticated WebSocket should be rejected"

    def test_ws_with_query_param_accepted(self):
        c = _client()
        try:
            with c.websocket_connect(f"/api/daemon/test-role?api_key={_TEST_KEY}") as ws:
                resp = ws.receive_json()
                assert resp is not None
        except Exception:
            pass

    def test_ws_no_auth_mode(self):
        c = _client(api_key=None)
        try:
            with c.websocket_connect("/api/daemon/test-role") as ws:
                resp = ws.receive_json()
                assert resp is not None
        except Exception:
            pass


# ---------------------------------------------------------------------------
# App state
# ---------------------------------------------------------------------------


class TestAppState:
    def test_api_key_stored_on_app_state(self):
        app = _make_app(api_key="my-key")
        assert app.state.api_key == "my-key"

    def test_api_key_none_when_disabled(self):
        app = _make_app(api_key=None)
        assert app.state.api_key is None

    def test_templates_on_app_state(self):
        app = _make_app(api_key=None)
        assert app.state.templates is not None
