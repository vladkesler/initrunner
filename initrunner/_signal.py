"""Shared double-Ctrl-C shutdown signal handler."""

from __future__ import annotations

import os
import signal
import sys
import threading
from collections.abc import Callable


def install_shutdown_handler(
    stop_event: threading.Event,
    *,
    on_first_signal: Callable[[], None] | None = None,
) -> threading.Event:
    """Install a SIGINT/SIGTERM handler with double-signal force-exit.

    First signal: calls *on_first_signal* (if given), then sets *stop_event*.
    Second signal: calls ``os._exit(1)`` immediately.

    Returns the ``_shutting_down`` event for external inspection.
    """
    shutting_down = threading.Event()

    def _handler(signum: int, frame: object) -> None:
        if shutting_down.is_set():
            print("\nForce shutdown.", file=sys.stderr, flush=True)
            os._exit(1)
        shutting_down.set()
        if on_first_signal is not None:
            on_first_signal()
        stop_event.set()

    signal.signal(signal.SIGINT, _handler)
    signal.signal(signal.SIGTERM, _handler)
    return shutting_down
