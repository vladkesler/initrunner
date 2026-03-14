"""FastAPI application factory for the InitRunner dashboard."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from initrunner import __version__

if TYPE_CHECKING:
    from initrunner.audit.logger import AuditLogger
from initrunner.api.routes.audit import router as audit_router
from initrunner.api.routes.auth_ui import router as auth_ui_router
from initrunner.api.routes.chat_ui import router as chat_ui_router
from initrunner.api.routes.daemon import router as daemon_router
from initrunner.api.routes.daemon_ui import router as daemon_ui_router
from initrunner.api.routes.ingest import router as ingest_router
from initrunner.api.routes.ingest_ui import router as ingest_ui_router
from initrunner.api.routes.memory import router as memory_router
from initrunner.api.routes.memory_ui import router as memory_ui_router
from initrunner.api.routes.pages import router as pages_router
from initrunner.api.routes.quick_chat import router as quick_chat_router
from initrunner.api.routes.roles import router as roles_router

_logger = logging.getLogger(__name__)

_DASHBOARD_PORT = 8420
_MAX_BODY_BYTES = 2 * 1024 * 1024  # 2 MB

_PKG_DIR = Path(__file__).resolve().parent.parent
_TEMPLATES_DIR = _PKG_DIR / "_templates"
_STATIC_DIR = _PKG_DIR / "_static"


def create_dashboard_app(
    *,
    api_key: str | None = None,
    role_dirs: list[Path] | None = None,
    audit_logger: AuditLogger | None = None,
    secure_cookies: bool = False,
) -> FastAPI:
    """Build the FastAPI application with all dashboard routes.

    Serves Jinja2-rendered HTML pages at top-level paths and JSON API
    routes under ``/api/``.
    """
    from jinja2 import Environment, FileSystemLoader
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.templating import Jinja2Templates

    from initrunner.middleware import (
        all_paths_predicate,
        detail_error_response,
        make_auth_dispatch,
        make_body_size_dispatch,
        make_rate_limit_dispatch,
        make_security_headers_dispatch,
        prefix_predicate,
    )
    from initrunner.server.rate_limiter import TokenBucketRateLimiter

    app = FastAPI(
        title="InitRunner Dashboard",
        version=__version__,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )

    from initrunner.api.state import RoleRegistry

    app.state.api_key = api_key
    app.state.role_dirs = role_dirs or [Path(".")]
    app.state.role_registry = RoleRegistry(app.state.role_dirs)
    app.state.audit_logger = audit_logger
    app.state.secure_cookies = secure_cookies

    # Jinja2 templates
    env = Environment(loader=FileSystemLoader(str(_TEMPLATES_DIR)), autoescape=True)

    from initrunner.api.facehash import render_facehash_svg

    env.globals["facehash"] = render_facehash_svg
    env.globals["app_version"] = __version__

    templates = Jinja2Templates(env=env)
    app.state.templates = templates

    # --- Security middleware ---
    # Exempt paths: health, static assets, login page
    _auth_exempt = {"/api/health", "/login", "/logout", "/static", "/auth/session"}

    rate_limiter = TokenBucketRateLimiter(rate=120 / 60.0, burst=20)
    api_predicate = prefix_predicate("/api/", exclude={"/api/health"})

    # Body size limit on all paths except health and upload endpoints
    _base_body_predicate = all_paths_predicate(exclude={"/api/health"})

    def _body_size_applies(request) -> bool:
        if request.url.path.endswith("/chat/upload"):
            return False
        return _base_body_predicate(request)

    app.add_middleware(
        BaseHTTPMiddleware,  # type: ignore[arg-type]
        dispatch=make_body_size_dispatch(
            max_bytes=_MAX_BODY_BYTES,
            error_response=detail_error_response,
            applies_to=_body_size_applies,
        ),
    )

    # Rate limiting on /api/ routes
    app.add_middleware(
        BaseHTTPMiddleware,  # type: ignore[arg-type]
        dispatch=make_rate_limit_dispatch(
            rate_limiter=rate_limiter,
            applies_to=api_predicate,
            error_response=detail_error_response,
        ),
    )

    if api_key:
        # Auth predicate: apply to all paths except exempt ones
        def _auth_applies(request) -> bool:
            path = request.url.path
            if path in _auth_exempt:
                return False
            for prefix in ("/static/", "/api/health"):
                if path.startswith(prefix):
                    return False
            return True

        app.add_middleware(
            BaseHTTPMiddleware,  # type: ignore[arg-type]
            dispatch=make_auth_dispatch(
                api_key=api_key,
                applies_to=_auth_applies,
                error_response=detail_error_response,
                allow_query_param=True,
                allow_cookie=True,
                login_redirect="/login",
                secure_cookies=secure_cookies,
            ),
        )

    # Security headers on all responses
    app.add_middleware(
        BaseHTTPMiddleware,  # type: ignore[arg-type]
        dispatch=make_security_headers_dispatch(),
    )

    # --- Mount static files ---
    if _STATIC_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    # --- JSON API routes (unchanged) ---
    app.include_router(roles_router)
    app.include_router(audit_router)
    app.include_router(ingest_router)
    app.include_router(memory_router)
    app.include_router(daemon_router)

    # --- HTML page routes ---
    app.include_router(auth_ui_router)
    app.include_router(pages_router)
    app.include_router(quick_chat_router)
    app.include_router(chat_ui_router)
    app.include_router(memory_ui_router)
    app.include_router(ingest_ui_router)
    app.include_router(daemon_ui_router)

    # Health check
    @app.get("/api/health")
    async def health():
        return {"status": "ok"}

    _logger.info("Dashboard app created (templates from %s)", _TEMPLATES_DIR)
    return app


def run_dashboard(
    *,
    host: str = "127.0.0.1",
    port: int = _DASHBOARD_PORT,
    open_browser: bool = True,
    api_key: str | None = None,
    role_dirs: list[Path] | None = None,
    audit_logger: AuditLogger | None = None,
    secure_cookies: bool = False,
) -> None:
    """Start the dashboard server (blocking)."""
    import uvicorn

    app = create_dashboard_app(
        api_key=api_key,
        role_dirs=role_dirs,
        audit_logger=audit_logger,
        secure_cookies=secure_cookies,
    )

    if open_browser:
        import threading
        import time
        import webbrowser

        url = f"http://{host}:{port}"
        if api_key:
            import secrets

            nonce = secrets.token_urlsafe(32)
            app.state.auth_nonce = nonce
            url += f"/auth/session?nonce={nonce}"

        def _open():
            time.sleep(1.0)
            webbrowser.open(url)

        threading.Thread(target=_open, daemon=True).start()

    uvicorn.run(app, host=host, port=port, log_level="info")
