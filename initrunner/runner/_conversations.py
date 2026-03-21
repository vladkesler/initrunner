"""Thread-safe, LRU-bounded store for per-conversation message histories."""

from __future__ import annotations

import threading
import time
from collections import OrderedDict


class ConversationStore:
    """Thread-safe, LRU-bounded store for per-conversation message histories."""

    def __init__(self, *, max_conversations: int = 200, ttl_seconds: float = 3600) -> None:
        self._max = max_conversations
        self._ttl = ttl_seconds
        self._lock = threading.Lock()
        self._data: OrderedDict[str, tuple[float, list]] = OrderedDict()

    def get(self, key: str | None) -> list | None:
        """Return stored history if not expired, or None."""
        if key is None:
            return None
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                return None
            ts, messages = entry
            if time.monotonic() - ts > self._ttl:
                del self._data[key]
                return None
            # Mark as recently used
            self._data.move_to_end(key)
            return messages

    def put(self, key: str | None, messages: list) -> None:
        """Store history with current timestamp, evicting oldest if at capacity."""
        if key is None:
            return
        with self._lock:
            if key in self._data:
                self._data.move_to_end(key)
            self._data[key] = (time.monotonic(), messages)
            while len(self._data) > self._max:
                self._data.popitem(last=False)
