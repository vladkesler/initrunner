"""Unit tests for initrunner.middleware -- edge cases not covered by integration tests.

Integration tests in test_dashboard_security.py and test_server.py already cover basic
bearer auth pass/fail, rate limiting, body size, and HTTPS enforcement via real ASGI
apps.  This file focuses on unit-level edge cases: predicate logic, error formatting,
query-param auth with cookie redirect, login redirect (HTML vs JSON), cookie auth,
body size edge cases, security headers, and OpenAI error type mapping.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from initrunner.middleware import (
    all_paths_predicate,
    detail_error_response,
    make_auth_dispatch,
    make_body_size_dispatch,
    make_https_dispatch,
    make_rate_limit_dispatch,
    make_security_headers_dispatch,
    openai_error_response,
    prefix_predicate,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_request(
    path="/test",
    method="GET",
    headers=None,
    cookies=None,
    query_params=None,
):
    req = MagicMock()
    req.url = MagicMock()
    req.url.path = path
    req.method = method
    req.headers = headers or {}
    req.cookies = cookies or {}
    req.query_params = query_params or {}
    return req


def _make_call_next(status_code=200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.headers = {}
    call_next = AsyncMock(return_value=resp)
    return call_next, resp


# ---------------------------------------------------------------------------
# TestPrefixPredicate
# ---------------------------------------------------------------------------


class TestPrefixPredicate:
    def test_matching_prefix(self):
        pred = prefix_predicate("/api")
        req = _make_request(path="/api/roles")
        assert pred(req) is True

    def test_non_matching_prefix(self):
        pred = prefix_predicate("/api")
        req = _make_request(path="/health")
        assert pred(req) is False

    def test_exact_prefix(self):
        pred = prefix_predicate("/api")
        req = _make_request(path="/api")
        assert pred(req) is True

    def test_exclude_removes_matching_path(self):
        pred = prefix_predicate("/api", exclude={"/api/health"})
        req = _make_request(path="/api/health")
        assert pred(req) is False

    def test_exclude_does_not_affect_other_paths(self):
        pred = prefix_predicate("/api", exclude={"/api/health"})
        req = _make_request(path="/api/roles")
        assert pred(req) is True


# ---------------------------------------------------------------------------
# TestAllPathsPredicate
# ---------------------------------------------------------------------------


class TestAllPathsPredicate:
    def test_matches_any_path(self):
        pred = all_paths_predicate()
        assert pred(_make_request(path="/anything")) is True
        assert pred(_make_request(path="/")) is True
        assert pred(_make_request(path="/deep/nested/path")) is True

    def test_exclude_set_honoured(self):
        pred = all_paths_predicate(exclude={"/health", "/metrics"})
        assert pred(_make_request(path="/health")) is False
        assert pred(_make_request(path="/metrics")) is False

    def test_non_excluded_path_still_matches(self):
        pred = all_paths_predicate(exclude={"/health"})
        assert pred(_make_request(path="/api/roles")) is True


# ---------------------------------------------------------------------------
# TestDetailErrorResponse
# ---------------------------------------------------------------------------


class TestDetailErrorResponse:
    def test_401_format(self):
        resp = detail_error_response(401, "Unauthorized")
        assert resp.status_code == 401
        body = json.loads(bytes(resp.body))
        assert body == {"detail": "Unauthorized"}
        assert resp.media_type == "application/json"

    def test_429_format(self):
        resp = detail_error_response(429, "Too many requests")
        assert resp.status_code == 429
        body = json.loads(bytes(resp.body))
        assert body == {"detail": "Too many requests"}

    def test_500_format(self):
        resp = detail_error_response(500, "Internal error")
        assert resp.status_code == 500
        body = json.loads(bytes(resp.body))
        assert body == {"detail": "Internal error"}


# ---------------------------------------------------------------------------
# TestOpenaiErrorResponse
# ---------------------------------------------------------------------------


class TestOpenaiErrorResponse:
    def test_401_maps_to_authentication_error(self):
        resp = openai_error_response(401, "Bad key")
        body = json.loads(bytes(resp.body))
        assert body["error"]["type"] == "authentication_error"
        assert body["error"]["code"] == 401
        assert body["error"]["message"] == "Bad key"

    def test_403_maps_to_https_required(self):
        resp = openai_error_response(403, "Use HTTPS")
        body = json.loads(bytes(resp.body))
        assert body["error"]["type"] == "https_required"

    def test_429_maps_to_rate_limit_exceeded(self):
        resp = openai_error_response(429, "Slow down")
        body = json.loads(bytes(resp.body))
        assert body["error"]["type"] == "rate_limit_exceeded"

    def test_413_maps_to_request_too_large(self):
        resp = openai_error_response(413, "Too big")
        body = json.loads(bytes(resp.body))
        assert body["error"]["type"] == "request_too_large"

    def test_unknown_status_maps_to_api_error(self):
        resp = openai_error_response(500, "Oops")
        body = json.loads(bytes(resp.body))
        assert body["error"]["type"] == "api_error"
        assert resp.status_code == 500


# ---------------------------------------------------------------------------
# TestMakeAuthDispatch
# ---------------------------------------------------------------------------


class TestMakeAuthDispatch:
    @pytest.mark.asyncio
    async def test_bearer_auth_passes(self):
        dispatch = make_auth_dispatch(
            api_key="secret",
            applies_to=all_paths_predicate(),
            error_response=detail_error_response,
        )
        req = _make_request(headers={"authorization": "Bearer secret"})
        call_next, resp = _make_call_next()
        result = await dispatch(req, call_next)
        call_next.assert_awaited_once_with(req)
        assert result is resp

    @pytest.mark.asyncio
    async def test_missing_token_returns_401(self):
        dispatch = make_auth_dispatch(
            api_key="secret",
            applies_to=all_paths_predicate(),
            error_response=detail_error_response,
        )
        req = _make_request()
        call_next, _ = _make_call_next()
        result = await dispatch(req, call_next)
        assert result.status_code == 401
        call_next.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_non_applicable_path_skips_auth(self):
        dispatch = make_auth_dispatch(
            api_key="secret",
            applies_to=prefix_predicate("/api"),
            error_response=detail_error_response,
        )
        req = _make_request(path="/health")
        call_next, resp = _make_call_next()
        result = await dispatch(req, call_next)
        assert result is resp

    @pytest.mark.asyncio
    async def test_query_param_sets_cookie_and_redirects(self):
        dispatch = make_auth_dispatch(
            api_key="secret",
            applies_to=all_paths_predicate(),
            error_response=detail_error_response,
            allow_query_param=True,
            allow_cookie=True,
            cookie_name="initrunner_token",
            secure_cookies=False,
        )
        req = _make_request(
            path="/roles",
            query_params={"api_key": "secret"},
        )
        call_next, _ = _make_call_next()
        result = await dispatch(req, call_next)
        assert result.status_code == 302
        # Verify redirect goes to the same path
        assert result.headers.get("location") == "/roles"
        call_next.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_query_param_wrong_key_falls_through_to_401(self):
        dispatch = make_auth_dispatch(
            api_key="secret",
            applies_to=all_paths_predicate(),
            error_response=detail_error_response,
            allow_query_param=True,
        )
        req = _make_request(query_params={"api_key": "wrong"})
        call_next, _ = _make_call_next()
        result = await dispatch(req, call_next)
        assert result.status_code == 401

    @pytest.mark.asyncio
    async def test_cookie_auth_passes(self):
        dispatch = make_auth_dispatch(
            api_key="secret",
            applies_to=all_paths_predicate(),
            error_response=detail_error_response,
            allow_cookie=True,
            cookie_name="initrunner_token",
        )
        req = _make_request(cookies={"initrunner_token": "secret"})
        call_next, resp = _make_call_next()
        result = await dispatch(req, call_next)
        assert result is resp
        call_next.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_cookie_wrong_value_returns_401(self):
        dispatch = make_auth_dispatch(
            api_key="secret",
            applies_to=all_paths_predicate(),
            error_response=detail_error_response,
            allow_cookie=True,
        )
        req = _make_request(cookies={"initrunner_token": "wrong"})
        call_next, _ = _make_call_next()
        result = await dispatch(req, call_next)
        assert result.status_code == 401

    @pytest.mark.asyncio
    async def test_login_redirect_for_html_request(self):
        dispatch = make_auth_dispatch(
            api_key="secret",
            applies_to=all_paths_predicate(),
            error_response=detail_error_response,
            login_redirect="/login",
        )
        req = _make_request(
            path="/dashboard",
            headers={"accept": "text/html,application/xhtml+xml"},
        )
        call_next, _ = _make_call_next()
        result = await dispatch(req, call_next)
        assert result.status_code == 302
        location = result.headers.get("location", "")
        assert location == "/login?next=/dashboard"

    @pytest.mark.asyncio
    async def test_login_redirect_not_applied_for_json_request(self):
        dispatch = make_auth_dispatch(
            api_key="secret",
            applies_to=all_paths_predicate(),
            error_response=detail_error_response,
            login_redirect="/login",
        )
        req = _make_request(
            path="/api/data",
            headers={"accept": "application/json"},
        )
        call_next, _ = _make_call_next()
        result = await dispatch(req, call_next)
        # JSON clients get 401, not redirect
        assert result.status_code == 401

    @pytest.mark.asyncio
    async def test_timing_safe_comparison_wrong_key(self):
        """Ensure wrong key is rejected (hmac.compare_digest path)."""
        dispatch = make_auth_dispatch(
            api_key="correct-key",
            applies_to=all_paths_predicate(),
            error_response=detail_error_response,
        )
        req = _make_request(headers={"authorization": "Bearer wrong-key"})
        call_next, _ = _make_call_next()
        result = await dispatch(req, call_next)
        assert result.status_code == 401

    @pytest.mark.asyncio
    async def test_custom_error_message(self):
        dispatch = make_auth_dispatch(
            api_key="secret",
            applies_to=all_paths_predicate(),
            error_response=detail_error_response,
            error_message="Custom auth error",
        )
        req = _make_request()
        call_next, _ = _make_call_next()
        result = await dispatch(req, call_next)
        body = json.loads(result.body)
        assert body["detail"] == "Custom auth error"

    @pytest.mark.asyncio
    async def test_bearer_prefix_required(self):
        """Token without 'Bearer ' prefix should not be recognized."""
        dispatch = make_auth_dispatch(
            api_key="secret",
            applies_to=all_paths_predicate(),
            error_response=detail_error_response,
        )
        req = _make_request(headers={"authorization": "secret"})
        call_next, _ = _make_call_next()
        result = await dispatch(req, call_next)
        assert result.status_code == 401


# ---------------------------------------------------------------------------
# TestMakeRateLimitDispatch
# ---------------------------------------------------------------------------


class TestMakeRateLimitDispatch:
    @pytest.mark.asyncio
    async def test_allows_when_under_limit(self):
        limiter = MagicMock()
        limiter.allow.return_value = True
        dispatch = make_rate_limit_dispatch(
            rate_limiter=limiter,
            applies_to=all_paths_predicate(),
            error_response=detail_error_response,
        )
        req = _make_request()
        call_next, resp = _make_call_next()
        result = await dispatch(req, call_next)
        assert result is resp
        limiter.allow.assert_called_once()

    @pytest.mark.asyncio
    async def test_denies_when_over_limit(self):
        limiter = MagicMock()
        limiter.allow.return_value = False
        dispatch = make_rate_limit_dispatch(
            rate_limiter=limiter,
            applies_to=all_paths_predicate(),
            error_response=openai_error_response,
        )
        req = _make_request()
        call_next, _ = _make_call_next()
        result = await dispatch(req, call_next)
        assert result.status_code == 429
        body = json.loads(result.body)
        assert body["error"]["type"] == "rate_limit_exceeded"
        call_next.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_passthrough_for_non_applicable_path(self):
        limiter = MagicMock()
        limiter.allow.return_value = False  # would deny if checked
        dispatch = make_rate_limit_dispatch(
            rate_limiter=limiter,
            applies_to=prefix_predicate("/api"),
            error_response=detail_error_response,
        )
        req = _make_request(path="/health")
        call_next, resp = _make_call_next()
        result = await dispatch(req, call_next)
        assert result is resp
        limiter.allow.assert_not_called()


# ---------------------------------------------------------------------------
# TestMakeBodySizeDispatch
# ---------------------------------------------------------------------------


class TestMakeBodySizeDispatch:
    @pytest.mark.asyncio
    async def test_post_over_limit_rejected(self):
        dispatch = make_body_size_dispatch(
            max_bytes=1024,
            error_response=detail_error_response,
        )
        req = _make_request(
            method="POST",
            headers={"content-length": "2048"},
        )
        call_next, _ = _make_call_next()
        result = await dispatch(req, call_next)
        assert result.status_code == 413

    @pytest.mark.asyncio
    async def test_put_over_limit_rejected(self):
        dispatch = make_body_size_dispatch(
            max_bytes=1024,
            error_response=detail_error_response,
        )
        req = _make_request(
            method="PUT",
            headers={"content-length": "2048"},
        )
        call_next, _ = _make_call_next()
        result = await dispatch(req, call_next)
        assert result.status_code == 413

    @pytest.mark.asyncio
    async def test_patch_over_limit_rejected(self):
        dispatch = make_body_size_dispatch(
            max_bytes=1024,
            error_response=detail_error_response,
        )
        req = _make_request(
            method="PATCH",
            headers={"content-length": "5000"},
        )
        call_next, _ = _make_call_next()
        result = await dispatch(req, call_next)
        assert result.status_code == 413

    @pytest.mark.asyncio
    async def test_get_passthrough_regardless_of_size(self):
        dispatch = make_body_size_dispatch(
            max_bytes=100,
            error_response=detail_error_response,
        )
        req = _make_request(
            method="GET",
            headers={"content-length": "999999"},
        )
        call_next, resp = _make_call_next()
        result = await dispatch(req, call_next)
        assert result is resp

    @pytest.mark.asyncio
    async def test_no_content_length_passes_through(self):
        """POST without Content-Length header should not be rejected."""
        dispatch = make_body_size_dispatch(
            max_bytes=100,
            error_response=detail_error_response,
        )
        req = _make_request(method="POST", headers={})
        call_next, resp = _make_call_next()
        result = await dispatch(req, call_next)
        assert result is resp

    @pytest.mark.asyncio
    async def test_invalid_content_length_passes_through(self):
        """Non-numeric Content-Length should not crash; request passes through."""
        dispatch = make_body_size_dispatch(
            max_bytes=100,
            error_response=detail_error_response,
        )
        req = _make_request(
            method="POST",
            headers={"content-length": "not-a-number"},
        )
        call_next, resp = _make_call_next()
        result = await dispatch(req, call_next)
        assert result is resp

    @pytest.mark.asyncio
    async def test_applies_to_filter_skips_non_matching_path(self):
        dispatch = make_body_size_dispatch(
            max_bytes=100,
            error_response=detail_error_response,
            applies_to=prefix_predicate("/api"),
        )
        req = _make_request(
            path="/other",
            method="POST",
            headers={"content-length": "999999"},
        )
        call_next, resp = _make_call_next()
        result = await dispatch(req, call_next)
        assert result is resp


# ---------------------------------------------------------------------------
# TestMakeSecurityHeadersDispatch
# ---------------------------------------------------------------------------


class TestMakeSecurityHeadersDispatch:
    @pytest.mark.asyncio
    async def test_all_security_headers_present(self):
        dispatch = make_security_headers_dispatch()
        req = _make_request()
        call_next, resp = _make_call_next()
        result = await dispatch(req, call_next)
        assert result is resp
        assert resp.headers["X-Frame-Options"] == "DENY"
        assert resp.headers["X-Content-Type-Options"] == "nosniff"
        assert "default-src 'self'" in resp.headers["Content-Security-Policy"]

    @pytest.mark.asyncio
    async def test_headers_added_to_any_status_code(self):
        dispatch = make_security_headers_dispatch()
        req = _make_request()
        call_next, resp = _make_call_next(status_code=500)
        await dispatch(req, call_next)
        assert "X-Frame-Options" in resp.headers
        assert "X-Content-Type-Options" in resp.headers
        assert "Content-Security-Policy" in resp.headers


# ---------------------------------------------------------------------------
# TestMakeHttpsDispatch
# ---------------------------------------------------------------------------


class TestMakeHttpsDispatch:
    @pytest.mark.asyncio
    async def test_https_passes(self):
        dispatch = make_https_dispatch(
            applies_to=all_paths_predicate(),
            error_response=detail_error_response,
        )
        req = _make_request(headers={"x-forwarded-proto": "https"})
        call_next, resp = _make_call_next()
        result = await dispatch(req, call_next)
        assert result is resp

    @pytest.mark.asyncio
    async def test_http_rejected(self):
        dispatch = make_https_dispatch(
            applies_to=all_paths_predicate(),
            error_response=detail_error_response,
        )
        req = _make_request(headers={"x-forwarded-proto": "http"})
        call_next, _ = _make_call_next()
        result = await dispatch(req, call_next)
        assert result.status_code == 403

    @pytest.mark.asyncio
    async def test_missing_header_treated_as_non_https(self):
        dispatch = make_https_dispatch(
            applies_to=all_paths_predicate(),
            error_response=detail_error_response,
        )
        req = _make_request(headers={})
        call_next, _ = _make_call_next()
        result = await dispatch(req, call_next)
        assert result.status_code == 403

    @pytest.mark.asyncio
    async def test_non_applicable_path_passes(self):
        dispatch = make_https_dispatch(
            applies_to=prefix_predicate("/secure"),
            error_response=detail_error_response,
        )
        req = _make_request(path="/public", headers={})
        call_next, resp = _make_call_next()
        result = await dispatch(req, call_next)
        assert result is resp
