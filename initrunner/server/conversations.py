"""In-memory conversation store for server-side history tracking."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

from pydantic_ai.messages import ModelMessage

DEFAULT_TTL_SECONDS = 3600  # 1 hour


@dataclass
class ConversationState:
    messages: list[ModelMessage] = field(default_factory=list)
    last_access: float = field(default_factory=time.monotonic)


class ConversationStore:
    """Thread-safe in-memory store for conversation histories."""

    def __init__(
        self, ttl_seconds: float = DEFAULT_TTL_SECONDS, max_conversations: int = 0
    ) -> None:
        self._ttl = ttl_seconds
        self._max = max_conversations
        self._conversations: dict[str, ConversationState] = {}
        self._lock = threading.Lock()

    def get(self, conversation_id: str) -> list[ModelMessage] | None:
        """Return stored history for a conversation, or None if not found/expired."""
        self._cleanup()
        with self._lock:
            state = self._conversations.get(conversation_id)
            if state is None:
                return None
            state.last_access = time.monotonic()
            return list(state.messages)

    def save(self, conversation_id: str, messages: list) -> None:
        """Store updated history for a conversation."""
        with self._lock:
            self._conversations[conversation_id] = ConversationState(
                messages=list(messages),
                last_access=time.monotonic(),
            )
            # Evict oldest conversations when cap is reached
            if self._max > 0 and len(self._conversations) > self._max:
                oldest_id = min(
                    self._conversations,
                    key=lambda cid: self._conversations[cid].last_access,
                )
                del self._conversations[oldest_id]

    def _cleanup(self) -> None:
        """Evict conversations older than TTL (lazy, on access)."""
        now = time.monotonic()
        with self._lock:
            expired = [
                cid
                for cid, state in self._conversations.items()
                if (now - state.last_access) > self._ttl
            ]
            for cid in expired:
                del self._conversations[cid]

    def clear(self) -> None:
        """Remove all conversations."""
        with self._lock:
            self._conversations.clear()
