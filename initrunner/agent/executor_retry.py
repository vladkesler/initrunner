"""Retry and timeout resilience primitives for agent execution.

HTTP retries live at the transport layer via PydanticAI's tenacity transports:
every provider request (including streaming) retries transient status codes with
exponential backoff, honoring ``Retry-After`` headers. The client built here is
injected into provider construction in ``loader._build_single_model``.

The provider SDKs are mid-migration from ``httpx`` to ``httpx2`` and type-check
the client they are handed, so the client is built in the flavor the SDK will
accept. InitRunner's own HTTP tools are unaffected and still use httpx.
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
import httpx2

_logger = logging.getLogger(__name__)

_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}

# httpx2 is where the provider SDKs are heading and most already accept it, but
# anthropic takes *only* httpx2 while groq takes *only* legacy httpx, so there is
# no one client that serves every provider. This set shrinks to empty as the
# remaining SDKs move over.
_LEGACY_HTTPX_PROVIDERS = frozenset({"groq"})
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


def _raise_for_retryable_status(response: httpx.Response | httpx2.Response) -> None:
    """Raise ``HTTPStatusError`` only for transient status codes.

    Permanent errors (401, 403, 404, 422, ...) pass through untouched so the
    provider SDK surfaces them immediately instead of burning retry attempts.
    """
    if response.status_code in _RETRYABLE_STATUS_CODES:
        response.raise_for_status()


def _retry_config(error_cls: type[Exception], *, attempts: int, max_wait: float):
    """Shared backoff policy: retry *error_cls* with Retry-After aware waits."""
    from pydantic_ai.retries import RetryConfig, wait_retry_after
    from tenacity import retry_if_exception_type, stop_after_attempt

    return RetryConfig(
        retry=retry_if_exception_type(error_cls),
        wait=wait_retry_after(max_wait=max_wait),
        stop=stop_after_attempt(attempts),
        reraise=True,
    )


def _build_httpx2_client(*, attempts: int, max_wait: float) -> httpx2.AsyncClient:
    from pydantic_ai.models import DEFAULT_HTTP_TIMEOUT, get_user_agent
    from pydantic_ai.retries import AsyncHTTPX2TenacityTransport

    return httpx2.AsyncClient(
        transport=AsyncHTTPX2TenacityTransport(
            _retry_config(httpx2.HTTPStatusError, attempts=attempts, max_wait=max_wait),
            validate_response=_raise_for_retryable_status,
        ),
        # Mirror pydantic_ai's own client defaults: the library's 5s default
        # connect timeout would kill long model calls.
        timeout=httpx2.Timeout(timeout=DEFAULT_HTTP_TIMEOUT, connect=5),
        headers={"User-Agent": get_user_agent()},
    )


def _build_legacy_client(*, attempts: int, max_wait: float) -> httpx.AsyncClient:
    from pydantic_ai.models import DEFAULT_HTTP_TIMEOUT, get_user_agent
    from pydantic_ai.retries import AsyncTenacityTransport

    return httpx.AsyncClient(
        transport=AsyncTenacityTransport(
            _retry_config(httpx.HTTPStatusError, attempts=attempts, max_wait=max_wait),
            validate_response=_raise_for_retryable_status,
        ),
        timeout=httpx.Timeout(timeout=DEFAULT_HTTP_TIMEOUT, connect=5),
        headers={"User-Agent": get_user_agent()},
    )


def build_retrying_async_client(
    provider: str,
    *,
    attempts: int = _DEFAULT_ATTEMPTS,
    max_wait: float = _DEFAULT_MAX_WAIT,
) -> httpx.AsyncClient | httpx2.AsyncClient:
    """Build an async client for *provider* that retries transient errors.

    Wraps the default transport in PydanticAI's tenacity transport with
    exponential backoff capped by ``Retry-After`` header support. Retries
    status codes {429, 500, 502, 503, 504} up to *attempts* total tries.

    The client speaks httpx2 unless *provider*'s SDK has not migrated yet, in
    which case it speaks legacy httpx. Handing an SDK the wrong one is a
    ``TypeError`` from inside its constructor rather than a degraded mode, so
    the choice is made here rather than left to the caller.
    """
    if provider in _LEGACY_HTTPX_PROVIDERS:
        return _build_legacy_client(attempts=attempts, max_wait=max_wait)
    return _build_httpx2_client(attempts=attempts, max_wait=max_wait)
