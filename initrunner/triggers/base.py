"""Base types for the trigger system."""

from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class TriggerEvent:
    trigger_type: str
    prompt: str
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    metadata: dict[str, str] = field(default_factory=dict)


class TriggerBase(ABC):
    """Abstract base for all triggers. Runs in a daemon thread."""

    def __init__(self, callback: Callable[[TriggerEvent], None]) -> None:
        self._callback = callback
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=10)

    @abstractmethod
    def _run(self) -> None:
        """Main loop — must check self._stop_event regularly."""
