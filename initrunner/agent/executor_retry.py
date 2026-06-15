"""Retry and timeout resilience primitives for agent execution.

HTTP retries live at the httpx transport layer via PydanticAI's
``AsyncTenacityTransport``: every provider request (including streaming)
retries transient status codes with exponential backoff, honoring
``Retry-After`` headers. The client built here is injected into provider
construction in ``loader._build_single_model``.
"""

from __future__ import annotations

import atexit
import contextvars
import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as _FuturesTimeout
from typing import TypeVar

import httpx

_logger = logging.getLogger(__name__)

_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
_DEFAULT_ATTEMPTS = 3
_DEFAULT_MAX_WAIT = 60.0  # seconds; cap for Retry-After + backoff waits

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


def _raise_for_retryable_status(response: httpx.Response) -> None:
    """Raise ``HTTPStatusError`` only for transient status codes.

    Permanent errors (401, 403, 404, 422, ...) pass through untouched so the
    provider SDK surfaces them immediately instead of burning retry attempts.
    """
    if response.status_code in _RETRYABLE_STATUS_CODES:
        response.raise_for_status()


def build_retrying_async_client(
    *,
    attempts: int = _DEFAULT_ATTEMPTS,
    max_wait: float = _DEFAULT_MAX_WAIT,
) -> httpx.AsyncClient:
    """Build an ``httpx.AsyncClient`` that retries transient provider errors.

    Wraps the default transport in PydanticAI's ``AsyncTenacityTransport``
    with exponential backoff capped by ``Retry-After`` header support
    (``wait_retry_after``). Retries status codes {429, 500, 502, 503, 504}
    up to ``attempts`` total tries.
    """
    from pydantic_ai.models import DEFAULT_HTTP_TIMEOUT, get_user_agent
    from pydantic_ai.retries import AsyncTenacityTransport, RetryConfig, wait_retry_after
    from tenacity import retry_if_exception_type, stop_after_attempt

    transport = AsyncTenacityTransport(
        RetryConfig(
            retry=retry_if_exception_type(httpx.HTTPStatusError),
            wait=wait_retry_after(max_wait=max_wait),
            stop=stop_after_attempt(attempts),
            reraise=True,
        ),
        validate_response=_raise_for_retryable_status,
    )
    # Mirror pydantic_ai.models.create_async_http_client defaults: httpx's own
    # 5s default timeout would kill long model calls.
    return httpx.AsyncClient(
        transport=transport,
        timeout=httpx.Timeout(timeout=DEFAULT_HTTP_TIMEOUT, connect=5),
        headers={"User-Agent": get_user_agent()},
    )
