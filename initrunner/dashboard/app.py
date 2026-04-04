"""FastAPI application factory for the InitRunner dashboard."""

from __future__ import annotations

import hashlib
import hmac
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, Form, Query, Request  # type: ignore[import-not-found]
from fastapi.middleware.cors import CORSMiddleware  # type: ignore[import-not-found]
from fastapi.responses import (  # type: ignore[import-not-found]
    FileResponse,
    HTMLResponse,
    JSONResponse,
)
from fastapi.staticfiles import StaticFiles  # type: ignore[import-not-found]
from starlette.middleware.base import BaseHTTPMiddleware  # type: ignore[import-not-found]
from starlette.responses import RedirectResponse

from initrunner.dashboard.config import DashboardSettings
from initrunner.dashboard.deps import (
    FlowCache,
    RoleCache,
    SkillCache,
    TeamCache,
    get_flow_cache,
    get_role_cache,
    get_skill_cache,
    get_team_cache,
)
from initrunner.dashboard.login import render_login_page
from initrunner.dashboard.schemas import HealthResponse

_logger = logging.getLogger(__name__)

_STATIC_DIR = Path(__file__).parent / "_static"


def create_app(settings: DashboardSettings | None = None) -> FastAPI:
    settings = settings or DashboardSettings()
    role_cache = RoleCache(settings)
    flow_cache = FlowCache(settings)
    team_cache = TeamCache(settings)
    skill_cache = SkillCache(settings)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        import asyncio

        await asyncio.to_thread(role_cache.refresh)
        await asyncio.to_thread(flow_cache.refresh)
        await asyncio.to_thread(team_cache.refresh)
        await asyncio.to_thread(skill_cache.refresh)
        yield

    app = FastAPI(
        title="InitRunner Dashboard",
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )

    # CORS -- allow the Vite dev server during development
    app.add_middleware(
        CORSMiddleware,  # type: ignore[arg-type]
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # -- Dependency overrides: inject caches as singletons ------------------
    app.dependency_overrides[get_role_cache] = lambda: role_cache
    app.dependency_overrides[get_flow_cache] = lambda: flow_cache
    app.dependency_overrides[get_team_cache] = lambda: team_cache
    app.dependency_overrides[get_skill_cache] = lambda: skill_cache

    # -- Health endpoint ----------------------------------------------------
    @app.get("/api/health", tags=["health"])
    async def health() -> HealthResponse:
        from initrunner import __version__

        return HealthResponse(status="ok", version=__version__)

    # -- Auth routes (always registered; no-ops when auth is disabled) ------
    if settings.api_key:
        _expected_key: str = settings.api_key
        _COOKIE_NAME = "initrunner_token"
        # Derive a session token from the API key so the raw key never
        # appears in cookies, browser storage, or proxy logs.
        _session_token: str = hmac.new(
            _expected_key.encode(), b"initrunner-session", hashlib.sha256
        ).hexdigest()

        def _safe_next(value: str) -> str:
            """Validate *next* is a relative path to prevent open redirects."""
            parsed = urlparse(value)
            if parsed.scheme or parsed.netloc:
                return "/"
            return value if value.startswith("/") else "/"

        def _is_https(request: Request) -> bool:
            """True when the request arrived over HTTPS (direct or proxied)."""
            if request.url.scheme == "https":
                return True
            return request.headers.get("x-forwarded-proto", "") == "https"

        @app.get("/login", include_in_schema=False)
        async def login_page(
            next: str = Query("/", alias="next"),
            error: str | None = Query(None),
        ) -> HTMLResponse:
            return HTMLResponse(render_login_page(error=error, next_path=_safe_next(next)))

        @app.post("/login", include_in_schema=False, response_model=None)
        async def login_submit(
            request: Request,
            api_key: str = Form(...),
            next: str = Form("/"),
        ) -> HTMLResponse | RedirectResponse:
            safe_next = _safe_next(next)
            if not hmac.compare_digest(api_key, _expected_key):
                return HTMLResponse(
                    render_login_page(error="Invalid API key.", next_path=safe_next),
                    status_code=401,
                )
            resp = RedirectResponse(safe_next, status_code=303)
            resp.set_cookie(
                key=_COOKIE_NAME,
                value=_session_token,
                httponly=True,
                samesite="strict",
                secure=_is_https(request),
            )
            return resp

        @app.post("/logout", include_in_schema=False)
        async def logout() -> RedirectResponse:
            resp = RedirectResponse("/login", status_code=303)
            resp.delete_cookie(key=_COOKIE_NAME)
            return resp

    # -- Register API routers -----------------------------------------------
    from initrunner.dashboard.routers.agents import router as agents_router
    from initrunner.dashboard.routers.audit import router as audit_router
    from initrunner.dashboard.routers.builder import router as builder_router
    from initrunner.dashboard.routers.flow import router as flow_router
    from initrunner.dashboard.routers.flow_builder import router as flow_builder_router
    from initrunner.dashboard.routers.ingest import router as ingest_router
    from initrunner.dashboard.routers.mcp_hub import router as mcp_hub_router
    from initrunner.dashboard.routers.memory import router as memory_router
    from initrunner.dashboard.routers.providers import router as providers_router
    from initrunner.dashboard.routers.runs import router as runs_router
    from initrunner.dashboard.routers.skills import router as skills_router
    from initrunner.dashboard.routers.system import router as system_router
    from initrunner.dashboard.routers.team_builder import router as team_builder_router
    from initrunner.dashboard.routers.team_ingest import router as team_ingest_router
    from initrunner.dashboard.routers.team_memory import router as team_memory_router
    from initrunner.dashboard.routers.teams import router as teams_router

    app.include_router(agents_router)
    app.include_router(runs_router)
    app.include_router(audit_router)
    app.include_router(memory_router)
    app.include_router(ingest_router)
    app.include_router(providers_router)
    app.include_router(system_router)
    app.include_router(builder_router)
    app.include_router(flow_router)
    app.include_router(flow_builder_router)
    app.include_router(teams_router)
    app.include_router(team_builder_router)
    app.include_router(team_memory_router)
    app.include_router(team_ingest_router)
    app.include_router(skills_router)
    app.include_router(mcp_hub_router)

    # -- Static file serving (production) -----------------------------------
    if _STATIC_DIR.is_dir():
        _index = _STATIC_DIR / "index.html"

        # SPA fallback + cache control
        @app.middleware("http")
        async def spa_fallback(request: Request, call_next):
            response = await call_next(request)
            path = request.url.path

            # Never cache index.html -- hashed assets in _app/immutable/ are safe to cache
            if path == "/" or path == "/index.html":
                response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"

            if response.status_code == 404 and not path.startswith("/api") and _index.exists():
                return FileResponse(
                    _index,
                    media_type="text/html",
                    headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
                )
            return response

        app.mount("/", StaticFiles(directory=str(_STATIC_DIR), html=True), name="static")
        _logger.info("Serving dashboard UI from %s", _STATIC_DIR)
    else:
        _logger.info(
            "No _static/ directory found -- API-only mode. Run the frontend dev server separately."
        )

    # -- Error handler for clean JSON errors --------------------------------
    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):
        _logger.exception("Unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(
            {"detail": "Internal server error"},
            status_code=500,
        )

    # -- Auth middleware (outermost -- added last so it runs first) ---------
    if _auth_key := settings.api_key:
        from initrunner.middleware import (
            all_paths_predicate,
            detail_error_response,
            make_auth_dispatch,
        )

        _auth_session_token = hmac.new(
            _auth_key.encode(), b"initrunner-session", hashlib.sha256
        ).hexdigest()
        app.add_middleware(
            BaseHTTPMiddleware,  # type: ignore[arg-type]
            dispatch=make_auth_dispatch(
                api_key=_auth_key,
                applies_to=all_paths_predicate(exclude={"/login", "/api/health"}),
                error_response=detail_error_response,
                error_message="Invalid API key",
                allow_query_param=False,
                allow_cookie=True,
                cookie_token=_auth_session_token,
                login_redirect="/login",
            ),
        )
        _logger.info("Dashboard authentication enabled")

    return app
