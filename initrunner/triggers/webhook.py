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

logger = logging.getLogger(__name__)

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
            logger.debug(
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

            content_length = request.headers.get("content-length")
            if content_length:
                try:
                    if int(content_length) > _MAX_BODY_BYTES:
                        return JSONResponse({"error": "payload too large"}, status_code=413)
                except ValueError:
                    pass

            body = await request.body()

            if len(body) > _MAX_BODY_BYTES:
                return JSONResponse({"error": "payload too large"}, status_code=413)

            if config.secret:
                sig_header = request.headers.get("x-hub-signature-256", "")
                expected = (
                    "sha256=" + hmac.new(config.secret.encode(), body, hashlib.sha256).hexdigest()
                )
                if not hmac.compare_digest(sig_header, expected):
                    return JSONResponse({"error": "invalid signature"}, status_code=403)

            event = TriggerEvent(
                trigger_type="webhook",
                prompt=body.decode("utf-8", errors="replace"),
                metadata={"path": config.path},
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
                logger.warning(
                    "Webhook server thread still alive after forced stop"
                    " (port %d may remain bound)",
                    self._config.port,
                )
