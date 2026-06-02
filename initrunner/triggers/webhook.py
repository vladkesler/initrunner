"""Webhook trigger using starlette + uvicorn in a thread."""

from __future__ import annotations

import hashlib
import hmac
import logging
from collections.abc import Callable

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from initrunner.agent.schema.triggers import WebhookTriggerConfig
from initrunner.triggers.base import TriggerBase, TriggerEvent

_logger = logging.getLogger(__name__)

_MAX_BODY_BYTES = 1_048_576  # 1 MB


class WebhookTrigger(TriggerBase):
    """Fires when an HTTP webhook is received."""

    def __init__(
        self, config: WebhookTriggerConfig, callback: Callable[[TriggerEvent], None]
    ) -> None:
        super().__init__(callback)
        self._config = config
        self._server: uvicorn.Server | None = None

    def _run(self) -> None:
        from initrunner.server.rate_limiter import TokenBucketRateLimiter

        config = self._config
        if config.secret:
            _logger.debug(
                "Webhook secret configured (X-Hub-Signature-256), length=%d",
                len(config.secret),
            )
        rate_limiter = TokenBucketRateLimiter(
            rate=config.rate_limit_rpm / 60.0,
            burst=max(1, config.rate_limit_rpm // 6),  # ~10-second burst
        )

        async def handle(request: Request) -> JSONResponse:
            if request.method != config.method:
                return JSONResponse({"error": "method not allowed"}, status_code=405)

            if not rate_limiter.allow():
                return JSONResponse({"error": "rate limit exceeded"}, status_code=429)

            from initrunner.middleware import read_body_capped

            # Bounded read: a chunked request omits Content-Length, so the header
            # check alone is bypassable -- cap the bytes actually received.
            body = await read_body_capped(request, _MAX_BODY_BYTES)
            if body is None:
                return JSONResponse({"error": "payload too large"}, status_code=413)

            if config.secret:
                sig_header = request.headers.get("x-hub-signature-256", "")
                expected = (
                    "sha256=" + hmac.new(config.secret.encode(), body, hashlib.sha256).hexdigest()
                )
                if not hmac.compare_digest(sig_header, expected):
                    return JSONResponse({"error": "invalid signature"}, status_code=403)

            # Never trust a client-supplied principal: it would flow into the
            # HMAC-chained audit trail as the run's actor. Record the claim as
            # untrusted metadata instead of adopting it as the identity.
            metadata = {"path": config.path}
            claimed_principal = request.headers.get("x-principal-id")
            if claimed_principal:
                metadata["claimed_principal_id"] = claimed_principal
            event = TriggerEvent(
                trigger_type="webhook",
                prompt=body.decode("utf-8", errors="replace"),
                metadata=metadata,
                principal_id=None,
            )
            self._callback(event)
            return JSONResponse({"status": "ok"})

        app = Starlette(routes=[Route(config.path, handle, methods=[config.method])])
        uv_config = uvicorn.Config(app, host="127.0.0.1", port=config.port, log_level="warning")
        self._server = uvicorn.Server(uv_config)
        self._server.run()

    def stop(self) -> None:
        if self._server is not None:
            self._server.should_exit = True
        super().stop()
        if self._thread is not None and self._thread.is_alive():
            if self._server is not None:
                self._server.force_exit = True
            self._thread.join(timeout=5)
            if self._thread.is_alive():
                _logger.warning(
                    "Webhook server thread still alive after forced stop"
                    " (port %d may remain bound)",
                    self._config.port,
                )
