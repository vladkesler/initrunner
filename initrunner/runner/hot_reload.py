"""Hot-reload watcher for role YAML and skill files in daemon mode."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from pathlib import Path

_logger = logging.getLogger(__name__)


class RoleReloader:
    """Watches role YAML and skill files, invoking a callback on changes.

    Runs in a daemon thread. Fail-open: callback exceptions are logged but
    never crash the watcher.
    """

    def __init__(
        self,
        paths: list[Path],
        on_reload: Callable[[Path], None],
        *,
        role_path: Path,
        debounce_ms: int = 1000,
    ) -> None:
        self._paths = list(paths)
        self._on_reload = on_reload
        self._role_path = role_path
        self._debounce_ms = debounce_ms
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def start(self) -> None:
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="role-hot-reloader")
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=10)

    def set_watched_paths(self, paths: list[Path]) -> None:
        """Update the set of watched paths (triggers a watcher restart)."""
        with self._lock:
            self._paths = list(paths)

    def _run(self) -> None:
        from watchfiles import watch

        while not self._stop_event.is_set():
            with self._lock:
                watch_paths = list(self._paths)

            str_paths = [str(p) for p in watch_paths if p.exists()]
            if not str_paths:
                # Nothing to watch — wait a bit and retry
                self._stop_event.wait(2.0)
                continue

            try:
                for _changes in watch(
                    *str_paths,
                    stop_event=self._stop_event,
                    debounce=self._debounce_ms,
                ):
                    if self._stop_event.is_set():
                        break
                    try:
                        self._on_reload(self._role_path)
                    except Exception:
                        _logger.warning("Hot-reload callback failed", exc_info=True)
                    # Break the inner loop to restart watch() with possibly
                    # updated paths (new skills may have been added).
                    break
            except Exception:
                if not self._stop_event.is_set():
                    _logger.warning("Hot-reload watcher error", exc_info=True)
                    self._stop_event.wait(2.0)
