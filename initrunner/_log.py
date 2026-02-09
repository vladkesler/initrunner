"""Centralized logging for InitRunner."""

from __future__ import annotations

import logging
import sys
import threading

_lock = threading.Lock()
_setup_done = False


class _Formatter(logging.Formatter):
    """Format log records as ``[tag] message``, stripping the ``initrunner.`` prefix."""

    def format(self, record: logging.LogRecord) -> str:
        name = record.name
        if name.startswith("initrunner."):
            name = name[len("initrunner.") :]
        record.msg = f"[{name}] {record.msg}"
        return super().format(record)


def setup_logging(verbose: bool = False) -> None:
    """Configure the ``initrunner`` root logger (idempotent).

    Attaches a single ``StreamHandler(sys.stderr)`` with level WARNING
    (or DEBUG when *verbose* is True). Sets ``propagate = False`` so
    messages don't bubble to the root logger.
    """
    global _setup_done
    with _lock:
        if _setup_done:
            return
        logger = logging.getLogger("initrunner")
        logger.setLevel(logging.DEBUG if verbose else logging.WARNING)
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(_Formatter())
        logger.addHandler(handler)
        logger.propagate = False
        _setup_done = True


def get_logger(name: str) -> logging.Logger:
    """Return ``logging.getLogger(f"initrunner.{name}")``.

    Lazily calls :func:`setup_logging` on first use so that log output
    is routed to stderr even when callers skip explicit setup.
    """
    setup_logging()
    return logging.getLogger(f"initrunner.{name}")
