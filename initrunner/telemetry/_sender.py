"""Zero-dependency PostHog transport.

A small ``urllib`` POST to PostHog's capture API. Events are buffered in-process
and flushed in one batch on a daemon thread that is joined with a bounded
timeout, so a slow or unreachable network can never delay CLI exit. Every entry
point is best-effort and never raises.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
import urllib.request

_logger = logging.getLogger(__name__)

# Public, write-only project key (US Cloud, project 458252). Public client keys
# are designed to be embedded; this grants capture-only access, not read.
_DEFAULT_HOST = "https://us.i.posthog.com"
_PROJECT_KEY = "phc_xCsEKz7e2YnCzneVDsPd3moRDnK5PaHudUridGfAJCrw"

_SOCKET_TIMEOUT = 1.5  # seconds for the HTTP request itself
_JOIN_TIMEOUT = 1.0  # max seconds flush() will wait on the sender thread

_DEBUG_ENV = "INITRUNNER_TELEMETRY_DEBUG"
_HOST_ENV = "INITRUNNER_POSTHOG_HOST"
_KEY_ENV = "INITRUNNER_POSTHOG_KEY"

_pending: list[tuple[str, str, dict]] = []
_lock = threading.Lock()


def _host() -> str:
    return os.environ.get(_HOST_ENV, _DEFAULT_HOST).rstrip("/")


def _key() -> str:
    return os.environ.get(_KEY_ENV, _PROJECT_KEY)


def _debug() -> bool:
    value = os.environ.get(_DEBUG_ENV)
    return value is not None and value.strip().lower() not in {"", "0", "false"}


def enqueue(event: str, distinct_id: str, properties: dict) -> None:
    """Buffer one event for the next flush. Never raises."""
    try:
        with _lock:
            _pending.append((event, distinct_id, properties))
    except Exception:
        _logger.debug("telemetry enqueue failed", exc_info=True)


def _build_payload(items: list[tuple[str, str, dict]]) -> bytes:
    batch = [
        {"event": event, "distinct_id": distinct_id, "properties": properties}
        for (event, distinct_id, properties) in items
    ]
    return json.dumps({"api_key": _key(), "batch": batch}).encode("utf-8")


def _post(payload: bytes) -> None:
    url = f"{_host()}/batch/"
    if not url.startswith(("http://", "https://")):
        return  # refuse non-HTTP schemes (e.g. file://) from a hostile env override
    request = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json", "User-Agent": "initrunner-cli"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=_SOCKET_TIMEOUT) as response:
        response.read()


def _send(items: list[tuple[str, str, dict]]) -> None:
    try:
        payload = _build_payload(items)
        if _debug():
            sys.stderr.write("[initrunner telemetry] " + payload.decode("utf-8") + "\n")
            return
        _post(payload)
    except Exception:
        _logger.debug("telemetry send failed", exc_info=True)


def flush() -> None:
    """Send buffered events on a daemon thread, joined with a bounded timeout.

    Never raises; never blocks longer than ``_JOIN_TIMEOUT``.
    """
    try:
        with _lock:
            items = list(_pending)
            _pending.clear()
        if not items:
            return
        if _debug():
            _send(items)  # synchronous print, no network, no thread
            return
        thread = threading.Thread(target=_send, args=(items,), daemon=True)
        thread.start()
        thread.join(timeout=_JOIN_TIMEOUT)
    except Exception:
        _logger.debug("telemetry flush failed", exc_info=True)
