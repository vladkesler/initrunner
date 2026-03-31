"""Retry and timeout resilience primitives for agent execution."""

from __future__ import annotations

import asyncio
import atexit
import contextvars
import logging
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as _FuturesTimeout
from typing import Any, TypeVar

from pydantic_ai.exceptions import ModelHTTPError

_logger = logging.getLogger(__name__)

_RETRY_MAX_ATTEMPTS = 3
_RETRY_BACKOFF_BASE = 1.0  # seconds
_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}

_TIMEOUT_POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix="run_timeout")
atexit.register(_TIMEOUT_POOL.shutdown, wait=False)

_T = TypeVar("_T")


def _run_with_timeout(fn: Callable[[], _T], timeout: float) -> _T:
    """Run *fn* in a thread pool with a hard timeout (seconds).

    Uses ``copy_context()`` so that ContextVars (e.g. agent principal/engine)
    propagate to the pool thread where ``agent.run_sync()`` executes.
    """
    ctx = contextvars.copy_context()
    future = _TIMEOUT_POOL.submit(ctx.run, fn)
    try:
        return future.result(timeout=timeout)  # type: ignore[return-value]
    except _FuturesTimeout:
        raise TimeoutError(f"Run timed out after {int(timeout)}s") from None


def _should_retry(exc: ModelHTTPError, attempt: int) -> float | None:
    """Return delay seconds if retryable and more attempts remain, else None."""
    if exc.status_code not in _RETRYABLE_STATUS_CODES:
        return None
    if attempt >= _RETRY_MAX_ATTEMPTS - 1:
        return None
    delay = _RETRY_BACKOFF_BASE * (2**attempt)
    _logger.warning(
        "Retryable HTTP %d from model (attempt %d/%d), retrying in %.1fs",
        exc.status_code,
        attempt + 1,
        _RETRY_MAX_ATTEMPTS,
        delay,
    )
    return delay


def _retry_model_call(
    fn: Callable[[], _T],
    *,
    on_retry: Callable[[], None] | None = None,
) -> _T:
    """Call *fn* with retry-on-transient-HTTP-error logic.

    Retries up to ``_RETRY_MAX_ATTEMPTS`` times for status codes in
    ``_RETRYABLE_STATUS_CODES``, using exponential backoff.  Calls
    *on_retry* (if provided) before each retry attempt -- only when an
    actual retry will follow.
    """
    last_http_error: ModelHTTPError | None = None
    for attempt in range(_RETRY_MAX_ATTEMPTS):
        try:
            return fn()
        except ModelHTTPError as e:
            delay = _should_retry(e, attempt)
            if delay is None:
                raise
            last_http_error = e
            if on_retry is not None:
                on_retry()
            time.sleep(delay)
    raise last_http_error  # type: ignore[misc]


async def _retry_model_call_async(
    fn: Callable[..., Any],
    *,
    on_retry: Callable[[], None] | None = None,
) -> Any:
    """Async variant of ``_retry_model_call`` -- uses ``asyncio.sleep``."""
    last_http_error: ModelHTTPError | None = None
    for attempt in range(_RETRY_MAX_ATTEMPTS):
        try:
            return await fn()
        except ModelHTTPError as e:
            delay = _should_retry(e, attempt)
            if delay is None:
                raise
            last_http_error = e
            if on_retry is not None:
                on_retry()
            await asyncio.sleep(delay)
    raise last_http_error  # type: ignore[misc]
