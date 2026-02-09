"""Webhook sink — POST JSON payload to a URL."""

from __future__ import annotations

import os
import time

import httpx

from initrunner._log import get_logger
from initrunner.sinks.base import SinkBase, SinkPayload

logger = get_logger("sink.webhook")


class WebhookSink(SinkBase):
    def __init__(
        self,
        url: str,
        method: str = "POST",
        headers: dict[str, str] | None = None,
        timeout_seconds: int = 30,
        retry_count: int = 0,
    ) -> None:
        self._url = os.path.expandvars(url)
        self._method = method
        self._headers = {k: os.path.expandvars(v) for k, v in (headers or {}).items()}
        self._timeout = timeout_seconds
        self._retry_count = retry_count

    def send(self, payload: SinkPayload) -> None:
        attempts = 1 + self._retry_count
        last_err: Exception | None = None

        for attempt in range(attempts):
            try:
                with httpx.Client(timeout=self._timeout) as client:
                    response = client.request(
                        self._method,
                        self._url,
                        json=payload.to_dict(),
                        headers=self._headers,
                    )
                    response.raise_for_status()
                return
            except Exception as exc:
                last_err = exc
                if attempt < attempts - 1:
                    time.sleep(1)

        logger.error("Failed after %d attempt(s): %s", attempts, last_err)
