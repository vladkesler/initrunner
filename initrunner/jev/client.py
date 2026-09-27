"""The one module that imports ``typesafe_sdk``.

It holds a single process-wide sync client and turns SDK responses into plain
dataclasses, so the rest of InitRunner never touches SDK types. Every SDK
failure surfaces as :class:`JevError`; callers decide whether that means "fall
back" (routing) or "fail closed" (security checks).
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from initrunner.jev.questions import MODEL

_logger = logging.getLogger(__name__)

API_KEY_ENV = "TYPESAFE_API_KEY"
MODEL_ENV = "TYPESAFE_DEFAULT_MODEL"

# Interactive call sites (routing, screening, approval) sit on a user's path,
# so each HTTP attempt is short and the whole call, retries included, is capped.
_TIMEOUT_SECONDS = 5.0
_RETRY_BUDGET_SECONDS = 10.0


class JevError(Exception):
    """A judgment could not be obtained (missing key or extra, network, API error)."""

    def __init__(
        self, message: str, *, status: int | None = None, request_id: str | None = None
    ) -> None:
        super().__init__(message)
        self.status = status
        self.request_id = request_id


@dataclass(frozen=True)
class ChoiceResult:
    choice: str
    confidence: float
    probabilities: dict[str, float]


@dataclass(frozen=True)
class ScoreResult:
    score: float
    confidence: float
    probabilities: dict[int, float]


@dataclass(frozen=True)
class Judgment:
    """Jev's answers to one request, keyed by question name."""

    nouls: dict[str, float] = field(default_factory=dict)
    choices: dict[str, ChoiceResult] = field(default_factory=dict)
    scores: dict[str, ScoreResult] = field(default_factory=dict)
    model: str = ""
    request_id: str = ""
    input_tokens: int | None = None

    def to_dict(self) -> dict[str, Any]:
        """Raw answers for the audit trail, so thresholds can be re-tuned later."""
        return {
            "model": self.model,
            "request_id": self.request_id,
            "nouls": {k: round(v, 4) for k, v in self.nouls.items()},
            "choices": {
                k: {
                    "choice": c.choice,
                    "confidence": round(c.confidence, 4),
                    "probabilities": {o: round(p, 4) for o, p in c.probabilities.items()},
                }
                for k, c in self.choices.items()
            },
            "scores": {
                k: {
                    "score": round(s.score, 4),
                    "confidence": round(s.confidence, 4),
                    "probabilities": {lvl: round(p, 4) for lvl, p in s.probabilities.items()},
                }
                for k, s in self.scores.items()
            },
        }


_lock = threading.Lock()
_client: Any = None


def api_key() -> str | None:
    """The TypeSafe key from the environment or the vault, or ``None``."""
    from initrunner.credentials import get_resolver

    return get_resolver().get(API_KEY_ENV) or None


def model() -> str:
    """``TYPESAFE_DEFAULT_MODEL`` when set, otherwise the pinned :data:`MODEL`."""
    return os.environ.get(MODEL_ENV) or MODEL


def is_configured() -> bool:
    """True when the ``jev`` extra is installed and a key resolves."""
    from initrunner._compat import is_extra_installed

    return is_extra_installed("jev") and api_key() is not None


def _get_client() -> Any:
    global _client
    with _lock:
        if _client is not None:
            return _client
        try:
            from typesafe_sdk import (  # type: ignore[import-not-found]
                RetryPolicy,
                TypeSafeClient,
                TypeSafeError,
            )
        except ImportError:
            raise JevError(
                "typesafe-sdk is not installed: uv pip install initrunner[jev]"
            ) from None
        key = api_key()
        if key is None:
            raise JevError(
                f"{API_KEY_ENV} is not set. Export it or run: initrunner vault set {API_KEY_ENV}"
            )
        try:
            # The key is passed explicitly: the SDK only reads the env var itself,
            # so a key kept in the vault would otherwise never reach it.
            _client = TypeSafeClient(
                api_key=key,
                model=model(),
                timeout=_TIMEOUT_SECONDS,
                retry=RetryPolicy(max_retries=2, backoff_max=1.0, timeout=_RETRY_BUDGET_SECONDS),
            )
        except TypeSafeError as exc:
            raise JevError(f"Jev client could not be created: {exc}") from exc
        return _client


def reset() -> None:
    """Close and drop the shared client (tests, key changes)."""
    global _client
    with _lock:
        if _client is not None:
            try:
                _client.close()
            except Exception:
                _logger.debug("closing the Jev client failed", exc_info=True)
        _client = None


def ask(state: Any, questions: dict[str, Any]) -> Judgment:
    """Ask every question in one request and return the typed answers.

    Raises :class:`JevError` for anything that stops a judgment from coming
    back, including timeouts and connection failures.
    """
    client = _get_client()
    from typesafe_sdk import TypeSafeAPIError, TypeSafeError  # type: ignore[import-not-found]

    started = time.monotonic()
    try:
        response = client.system_one(state, questions)
    except TypeSafeAPIError as exc:
        raise JevError(
            f"Jev request failed with HTTP {exc.status}",
            status=exc.status,
            request_id=exc.request_id,
        ) from exc
    except TypeSafeError as exc:
        # Timeouts and connection errors subclass TimeoutError / ConnectionError;
        # they must not leak out as those, or callers treat them as model failures.
        raise JevError(f"Jev request failed: {exc}") from exc

    judgment = _to_judgment(response)
    _logger.debug(
        "jev answered %s in %d ms (model=%s request_id=%s input_tokens=%s)",
        ",".join(questions),
        int((time.monotonic() - started) * 1000),
        judgment.model,
        judgment.request_id,
        judgment.input_tokens,
    )
    return judgment


async def ask_async(state: Any, questions: dict[str, Any]) -> Judgment:
    """:func:`ask` on a worker thread.

    One sync client serves every caller; an async client would bind its
    connection pool to whichever event loop created it, and InitRunner starts a
    fresh loop per flow or team run.
    """
    import anyio

    return await anyio.to_thread.run_sync(ask, state, questions)  # type: ignore[unresolved-attribute]


def _to_judgment(response: Any) -> Judgment:
    usage = getattr(response, "usage", None)
    return Judgment(
        nouls={k: float(a.noul) for k, a in response.nouls.items()},
        choices={
            k: ChoiceResult(
                choice=a.choice,
                confidence=float(a.confidence),
                probabilities={o: float(p) for o, p in a.probabilities.items()},
            )
            for k, a in response.choices.items()
        },
        scores={
            k: ScoreResult(
                score=float(a.score),
                confidence=float(a.confidence),
                probabilities={int(lvl): float(p) for lvl, p in a.probabilities.items()},
            )
            for k, a in response.scores.items()
        },
        model=response.model,
        request_id=_request_id(response),
        input_tokens=usage.input_tokens if usage is not None else None,
    )


def _request_id(response: Any) -> str:
    # The SDK raises when the response carries no request-id header; a missing
    # id only costs us a log field, so it must not cost the judgment.
    try:
        return response.request_id or ""
    except Exception:
        return ""
