"""Tests for _ConversationStore in daemon runner."""

from __future__ import annotations

import threading
import time

from initrunner.runner.daemon import _ConversationStore


class TestConversationStore:
    def test_get_returns_none_for_unknown_key(self):
        store = _ConversationStore()
        assert store.get("unknown") is None

    def test_get_returns_none_for_none_key(self):
        store = _ConversationStore()
        assert store.get(None) is None

    def test_put_and_get(self):
        store = _ConversationStore()
        messages = [{"role": "user", "content": "hi"}]
        store.put("telegram:123", messages)
        assert store.get("telegram:123") == messages

    def test_put_none_key_is_noop(self):
        store = _ConversationStore()
        store.put(None, [{"role": "user", "content": "hi"}])
        # Should not raise or store anything

    def test_lru_eviction(self):
        store = _ConversationStore(max_conversations=2)
        store.put("a", [1])
        store.put("b", [2])
        store.put("c", [3])  # evicts "a"

        assert store.get("a") is None
        assert store.get("b") == [2]
        assert store.get("c") == [3]

    def test_get_refreshes_lru_order(self):
        store = _ConversationStore(max_conversations=2)
        store.put("a", [1])
        store.put("b", [2])
        # Access "a" to make it recently used
        store.get("a")
        store.put("c", [3])  # should evict "b" (oldest), not "a"

        assert store.get("a") == [1]
        assert store.get("b") is None
        assert store.get("c") == [3]

    def test_ttl_expiration(self):
        store = _ConversationStore(ttl_seconds=0.1)
        store.put("key", [1, 2, 3])
        assert store.get("key") == [1, 2, 3]

        time.sleep(0.15)
        assert store.get("key") is None

    def test_put_updates_existing_entry(self):
        store = _ConversationStore()
        store.put("key", [1])
        store.put("key", [1, 2])
        assert store.get("key") == [1, 2]

    def test_thread_safety(self):
        store = _ConversationStore(max_conversations=50)
        errors: list[Exception] = []

        def worker(prefix: str):
            try:
                for i in range(50):
                    key = f"{prefix}:{i}"
                    store.put(key, [i])
                    store.get(key)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(f"t{n}",)) for n in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"Concurrent errors: {errors}"
