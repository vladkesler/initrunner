"""Authentication helpers for the dashboard API."""

from __future__ import annotations

import hmac
import logging

from fastapi import WebSocket, status

_logger = logging.getLogger(__name__)


async def verify_websocket_auth(websocket: WebSocket) -> bool:
    """Check WebSocket auth before accept. Returns True if authorised.

    Checks ``?api_key=`` query param and ``Authorization: Bearer`` header.
    If the app has no ``api_key`` set (auth disabled), always returns True.
    On failure, closes with code 1008 (Policy Violation) **without** accepting.
    """
    api_key: str | None = getattr(websocket.app.state, "api_key", None)
    if not api_key:
        return True

    # Try query param first, then Authorization header
    token = websocket.query_params.get("api_key", "")
    if not token:
        auth_header = websocket.headers.get("authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]

    if token and hmac.compare_digest(token, api_key):
        return True

    _logger.warning("WebSocket auth failed from %s", websocket.client)
    await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
    return False
