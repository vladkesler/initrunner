"""Login page + cookie set/clear for dashboard auth."""

from __future__ import annotations

import hmac
from urllib.parse import urlparse

from fastapi import APIRouter, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse


def _safe_redirect_url(url: str, fallback: str = "/roles") -> str:
    """Reject absolute or protocol-relative URLs to prevent open redirects."""
    if not url:
        return fallback
    parsed = urlparse(url)
    if parsed.scheme or parsed.netloc or url.startswith("//"):
        return fallback
    if not url.startswith("/"):
        return fallback
    return url


router = APIRouter(tags=["auth-ui"])


@router.get("/auth/session")
async def nonce_login(request: Request, nonce: str = Query(...)):
    """Exchange a one-time nonce for an auth cookie. Used by open_browser."""
    expected = getattr(request.app.state, "auth_nonce", None)
    if not expected or not hmac.compare_digest(nonce, expected):
        return RedirectResponse("/login", status_code=302)
    # Consume the nonce (one-time use)
    request.app.state.auth_nonce = None
    api_key = request.app.state.api_key
    secure = getattr(request.app.state, "secure_cookies", False)
    response = RedirectResponse("/roles", status_code=302)
    response.set_cookie(
        key="initrunner_token",
        value=api_key,
        httponly=True,
        samesite="strict",
        secure=secure,
    )
    return response


@router.get("/login", response_class=HTMLResponse)
async def login_page(
    request: Request,
    error: str | None = Query(None),
    next: str | None = Query(None),
):
    """Login form page."""
    return request.app.state.templates.TemplateResponse(
        request, "auth/login.html", {"error": error, "next": next}
    )


@router.post("/login")
async def login_submit(
    request: Request,
    api_key: str = Form(...),
    next: str = Form("/roles"),
):
    """Validate API key and set auth cookie."""
    expected: str | None = request.app.state.api_key
    if expected is None:
        # Auth disabled — redirect directly
        return RedirectResponse(_safe_redirect_url(next), status_code=302)

    if not hmac.compare_digest(api_key, expected):
        return request.app.state.templates.TemplateResponse(
            request,
            "auth/login.html",
            {"error": "Invalid API key", "next": next},
            status_code=401,
        )

    secure = getattr(request.app.state, "secure_cookies", False)
    response = RedirectResponse(_safe_redirect_url(next), status_code=302)
    response.set_cookie(
        key="initrunner_token",
        value=api_key,
        httponly=True,
        samesite="strict",
        secure=secure,
    )
    return response


@router.get("/logout")
async def logout(request: Request):
    """Clear auth cookie and redirect to login."""
    response = RedirectResponse("/login", status_code=302)
    response.delete_cookie("initrunner_token")
    return response
