"""Base types for the trigger system."""

from __future__ import annotations

import logging
import threading
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

_logger = logging.getLogger(__name__)

CONVERSATIONAL_TRIGGER_TYPES: set[str] = set()


def register_conversational_trigger_type(platform: str) -> None:
    """Register a platform as conversational (has reply_fn, conversation history)."""
    CONVERSATIONAL_TRIGGER_TYPES.add(platform)


@dataclass
class TriggerEvent:
    trigger_type: str
    prompt: str
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    metadata: dict[str, str] = field(default_factory=dict)
    reply_fn: Callable[[str], None] | None = None
    principal_id: str | None = None
    principal_roles: list[str] = field(default_factory=list)

    @property
    def conversation_key(self) -> str | None:
        """Unique key for conversational triggers, None for stateless ones."""
        target = self.metadata.get("channel_target")
        if target and self.trigger_type in CONVERSATIONAL_TRIGGER_TYPES:
            return f"{self.trigger_type}:{target}"
        return None


def _chunk_text(text: str, limit: int) -> list[str]:
    """Split text into chunks that fit within platform message limit."""
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    while text:
        if len(text) <= limit:
            chunks.append(text)
            break
        # Split at last newline before limit, or hard-cut at limit
        split_at = text.rfind("\n", 0, limit)
        if split_at <= 0:
            split_at = limit
        chunks.append(text[:split_at])
        text = text[split_at:].lstrip("\n")
    return chunks


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
            if self._thread.is_alive():
                _logger.warning("%s trigger thread still alive after stop", self.__class__.__name__)

    @abstractmethod
    def _run(self) -> None:
        """Main loop — must check self._stop_event regularly."""


class ChannelAdapter(ABC):
    """Bidirectional adapter for a messaging platform.

    Unifies inbound (listen) and outbound (send) into a single per-platform
    class. Implementations handle their own async event loop internally.
    """

    @property
    @abstractmethod
    def platform(self) -> str:
        """Platform identifier (e.g. 'telegram', 'discord')."""

    @abstractmethod
    def start(self, callback: Callable[[TriggerEvent], None]) -> None:
        """Block and listen for inbound messages, calling *callback* for each.

        Only returns when :meth:`stop` is called from another thread.
        """

    @abstractmethod
    def stop(self) -> None:
        """Signal shutdown. :meth:`start` must return promptly after this."""

    @abstractmethod
    def send(self, target: str, text: str) -> None:
        """Send a message to an opaque adapter-defined route token.

        Thread-safe. Best-effort: must never raise.
        """


class ChannelTriggerBridge(TriggerBase):
    """Wraps a :class:`ChannelAdapter` so it satisfies :class:`TriggerBase`."""

    def __init__(self, adapter: ChannelAdapter, callback: Callable[[TriggerEvent], None]) -> None:
        super().__init__(callback)
        self._adapter = adapter
        register_conversational_trigger_type(adapter.platform)

    def _run(self) -> None:
        self._adapter.start(self._callback)

    def stop(self) -> None:
        self._adapter.stop()
        super().stop()
