"""Centralized logging for InitRunner."""

from __future__ import annotations

import logging
import os
import sys
import threading

_lock = threading.Lock()
_setup_done = False

LOG_LEVEL_ENV = "INITRUNNER_LOG_LEVEL"

# Raised alongside the ``initrunner`` logger at DEBUG so that provider traffic
# (the request that returned 401, the retry that timed out) is visible.
_PROVIDER_LOGGERS = ("httpx", "openai", "anthropic", "pydantic_ai")


class _Formatter(logging.Formatter):
    """Format log records as ``[tag] message``, stripping the ``initrunner.`` prefix."""

    def format(self, record: logging.LogRecord) -> str:
        name = record.name
        if name.startswith("initrunner."):
            name = name[len("initrunner.") :]
        record.msg = f"[{name}] {record.msg}"
        return super().format(record)


def _resolve_level(verbose: bool) -> tuple[int, str | None]:
    """Return the effective log level and any invalid env value to report.

    ``verbose`` wins over the environment; otherwise ``INITRUNNER_LOG_LEVEL``
    is read (level name or numeric), defaulting to WARNING.
    """
    if verbose:
        return logging.DEBUG, None
    raw = os.environ.get(LOG_LEVEL_ENV, "").strip()
    if not raw:
        return logging.WARNING, None
    if raw.isdigit():
        return int(raw), None
    level = logging.getLevelName(raw.upper())
    if isinstance(level, int):
        return level, None
    return logging.WARNING, raw


def setup_logging(verbose: bool = False) -> None:
    """Configure the ``initrunner`` root logger (idempotent).

    Attaches a single ``StreamHandler(sys.stderr)`` at WARNING, or at DEBUG
    when *verbose* is True, or at the level named by ``INITRUNNER_LOG_LEVEL``.
    Sets ``propagate = False`` so messages don't bubble to the root logger.
    At DEBUG the provider HTTP loggers are attached to the same handler.
    """
    global _setup_done
    with _lock:
        if _setup_done:
            return
        level, invalid = _resolve_level(verbose)
        logger = logging.getLogger("initrunner")
        logger.setLevel(level)
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(_Formatter())
        logger.addHandler(handler)
        logger.propagate = False
        if level <= logging.DEBUG:
            for name in _PROVIDER_LOGGERS:
                provider = logging.getLogger(name)
                provider.setLevel(logging.DEBUG)
                provider.addHandler(handler)
                provider.propagate = False
        _setup_done = True
    if invalid is not None:
        logging.getLogger("initrunner.log").warning(
            "ignoring invalid %s=%r (expected a level name such as DEBUG, INFO, WARNING)",
            LOG_LEVEL_ENV,
            invalid,
        )


def get_logger(name: str) -> logging.Logger:
    """Return ``logging.getLogger(f"initrunner.{name}")``.

    Lazily calls :func:`setup_logging` on first use so that log output
    is routed to stderr even when callers skip explicit setup.
    """
    setup_logging()
    return logging.getLogger(f"initrunner.{name}")
