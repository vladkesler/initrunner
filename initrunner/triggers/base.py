"""Base types for the trigger system."""

from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

CONVERSATIONAL_TRIGGER_TYPES: frozenset[str] = frozenset({"telegram", "discord"})


@dataclass
class TriggerEvent:
    trigger_type: str
    prompt: str
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    metadata: dict[str, str] = field(default_factory=dict)
    reply_fn: Callable[[str], None] | None = None

    @property
    def conversation_key(self) -> str | None:
        """Unique key for conversational triggers, None for stateless ones."""
        if self.trigger_type == "telegram":
            chat_id = self.metadata.get("chat_id")
            return f"telegram:{chat_id}" if chat_id else None
        if self.trigger_type == "discord":
            channel_id = self.metadata.get("channel_id")
            return f"discord:{channel_id}" if channel_id else None
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

    @abstractmethod
    def _run(self) -> None:
        """Main loop — must check self._stop_event regularly."""
