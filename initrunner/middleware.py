"""Shared security middleware factories for dashboard and server apps.

Each factory returns an ``async def dispatch(request, call_next)`` callable
suitable for ``BaseHTTPMiddleware``.
"""

from __future__ import annotations

import hmac
from collections.abc import Callable, Set

from starlette.requests import Request
from starlette.responses import Response

# ---------------------------------------------------------------------------
# Path predicates — control which routes a middleware applies to
# ---------------------------------------------------------------------------


def prefix_predicate(prefix: str, *, exclude: Set[str] | None = None) -> Callable[[Request], bool]:
    """Return True when the request path starts with *prefix* (and is not excluded)."""
    _exclude = exclude or frozenset()

    def _applies(request: Request) -> bool:
        path = request.url.path
        return path.startswith(prefix) and path not in _exclude

    return _applies


def all_paths_predicate(*, exclude: Set[str] | None = None) -> Callable[[Request], bool]:
    """Return True for all paths except those in *exclude*."""
    _exclude = exclude or frozenset()

    def _applies(request: Request) -> bool:
        return request.url.path not in _exclude

    return _applies


# ---------------------------------------------------------------------------
# Error formatters — control response body shape
# ---------------------------------------------------------------------------


def detail_error_response(status_code: int, message: str) -> Response:
    """``{"detail": "..."}`` format used by the dashboard API."""
    import json

    return Response(
        content=json.dumps({"detail": message}),
        status_code=status_code,
        media_type="application/json",
    )


_STATUS_TO_TYPE = {
    401: "authentication_error",
    403: "https_required",
    413: "request_too_large",
    429: "rate_limit_exceeded",
}


def openai_error_response(status_code: int, message: str) -> Response:
    """``{"error": {"message": ..., "type": ..., "code": N}}`` format."""
    from starlette.responses import JSONResponse

    error_type = _STATUS_TO_TYPE.get(status_code, "api_error")
    return JSONResponse(
        {"error": {"message": message, "type": error_type, "code": status_code}},
        status_code=status_code,
    )


# ---------------------------------------------------------------------------
# Middleware factories
# ---------------------------------------------------------------------------

ErrorResponseFn = Callable[[int, str], Response]
AppliesFn = Callable[[Request], bool]


def make_auth_dispatch(
    *,
    api_key: str,
    applies_to: AppliesFn,
    error_response: ErrorResponseFn,
    error_message: str = "Unauthorized",
    allow_query_param: bool = False,
    allow_cookie: bool = False,
    cookie_name: str = "initrunner_token",
    login_redirect: str | None = None,
    secure_cookies: bool = False,
):
    """Bearer token auth with timing-safe comparison.

    When *allow_cookie* is True, checks the ``initrunner_token`` cookie as
    an additional auth source.  When *login_redirect* is set and the request
    accepts HTML, unauthenticated requests are redirected to the login page
    instead of returning a JSON 401.
    """

    async def dispatch(request: Request, call_next) -> Response:
        if applies_to(request):
            token = ""
            auth_header = request.headers.get("authorization", "")
            if auth_header.startswith("Bearer "):
                token = auth_header[7:]
            if not token and allow_query_param:
                token = request.query_params.get("api_key", "")
                # If token came via query param, set cookie and redirect
                if token and hmac.compare_digest(token, api_key):
                    from starlette.responses import RedirectResponse

                    path = request.url.path or "/roles"
                    resp = RedirectResponse(path, status_code=302)
                    resp.set_cookie(
                        key=cookie_name,
                        value=token,
                        httponly=True,
                        samesite="strict",
                        secure=secure_cookies,
                    )
                    return resp
            if not token and allow_cookie:
                token = request.cookies.get(cookie_name, "")
            if not token or not hmac.compare_digest(token, api_key):
                # Redirect HTML requests to login page
                if login_redirect:
                    accept = request.headers.get("accept", "")
                    if "text/html" in accept:
                        from urllib.parse import quote

                        from starlette.responses import RedirectResponse

                        next_url = quote(str(request.url.path), safe="/")
                        return RedirectResponse(
                            f"{login_redirect}?next={next_url}", status_code=302
                        )
                return error_response(401, error_message)
        return await call_next(request)

    return dispatch


def make_rate_limit_dispatch(
    *,
    rate_limiter,
    applies_to: AppliesFn,
    error_response: ErrorResponseFn,
    error_message: str = "Too many requests",
):
    """Rate limit middleware using any object with an ``allow()`` method."""

    async def dispatch(request: Request, call_next) -> Response:
        if applies_to(request):
            if not rate_limiter.allow():
                return error_response(429, error_message)
        return await call_next(request)

    return dispatch


def make_body_size_dispatch(
    *,
    max_bytes: int,
    error_response: ErrorResponseFn,
    applies_to: AppliesFn | None = None,
    error_message: str = "Request body too large",
):
    """Reject POST/PUT/PATCH requests whose Content-Length exceeds *max_bytes*."""

    async def dispatch(request: Request, call_next) -> Response:
        if request.method in ("POST", "PUT", "PATCH"):
            if applies_to is None or applies_to(request):
                content_length = request.headers.get("content-length")
                if content_length:
                    try:
                        if int(content_length) > max_bytes:
                            return error_response(413, error_message)
                    except ValueError:
                        pass
        return await call_next(request)

    return dispatch


def make_security_headers_dispatch():
    """Add standard security headers to all responses."""

    _HEADERS = {
        "X-Frame-Options": "DENY",
        "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'"
        ),
    }

    async def dispatch(request: Request, call_next) -> Response:
        response = await call_next(request)
        for key, value in _HEADERS.items():
            response.headers[key] = value
        return response

    return dispatch


def make_https_dispatch(
    *,
    applies_to: AppliesFn,
    error_response: ErrorResponseFn,
    error_message: str = "HTTPS is required",
):
    """Reject non-HTTPS requests based on ``X-Forwarded-Proto``."""

    async def dispatch(request: Request, call_next) -> Response:
        if applies_to(request):
            proto = request.headers.get("x-forwarded-proto", "")
            if proto != "https":
                return error_response(403, error_message)
        return await call_next(request)

    return dispatch
