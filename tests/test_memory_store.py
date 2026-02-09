"""Tests for the memory store."""

import pytest
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    SystemPromptPart,
    TextPart,
    UserPromptPart,
)

from initrunner.stores.sqlite_vec import SqliteVecMemoryStore as MemoryStore
from initrunner.stores.sqlite_vec import _filter_system_prompts


def _make_request(content: str) -> ModelRequest:
    return ModelRequest(parts=[UserPromptPart(content=content)])


def _make_response(content: str) -> ModelResponse:
    return ModelResponse(parts=[TextPart(content=content)])


def _make_system_request(system: str, user: str) -> ModelRequest:
    return ModelRequest(parts=[SystemPromptPart(content=system), UserPromptPart(content=user)])


class TestCreateStore:
    def test_create_store(self, tmp_path):
        db_path = tmp_path / "test.db"
        with MemoryStore(db_path, dimensions=4):
            assert db_path.exists()

    def test_wal_mode(self, tmp_path):
        db_path = tmp_path / "test.db"
        with MemoryStore(db_path, dimensions=4) as store:
            row = store._conn.execute("PRAGMA journal_mode;").fetchone()  # type: ignore[attr-defined]
            assert row[0] == "wal"

    def test_context_manager(self, tmp_path):
        db_path = tmp_path / "test.db"
        with MemoryStore(db_path, dimensions=4) as store:
            store.add_memory("test", "general", [1.0, 0.0, 0.0, 0.0])
        assert db_path.exists()


class TestSessionPersistence:
    def test_save_and_load_session(self, tmp_path):
        db_path = tmp_path / "test.db"
        messages = [_make_request("hello"), _make_response("hi")]
        with MemoryStore(db_path, dimensions=4) as store:
            store.save_session("s1", "agent-a", messages)
            loaded = store.load_latest_session("agent-a")
        assert loaded is not None
        assert len(loaded) == 2
        assert isinstance(loaded[0], ModelRequest)
        assert isinstance(loaded[1], ModelResponse)

    def test_save_session_filters_system_prompt(self, tmp_path):
        db_path = tmp_path / "test.db"
        messages = [
            _make_system_request("You are helpful", "hello"),
            _make_response("hi"),
        ]
        with MemoryStore(db_path, dimensions=4) as store:
            store.save_session("s1", "agent-a", messages)
            loaded = store.load_latest_session("agent-a")
        assert loaded is not None
        # The system prompt part should be stripped
        request = loaded[0]
        assert isinstance(request, ModelRequest)
        assert len(request.parts) == 1
        assert isinstance(request.parts[0], UserPromptPart)

    def test_load_session_respects_max_messages(self, tmp_path):
        db_path = tmp_path / "test.db"
        messages = []
        for i in range(10):
            messages.append(_make_request(f"q{i}"))
            messages.append(_make_response(f"a{i}"))
        with MemoryStore(db_path, dimensions=4) as store:
            store.save_session("s1", "agent-a", messages)
            loaded = store.load_latest_session("agent-a", max_messages=4)
        assert loaded is not None
        assert len(loaded) == 4

    def test_load_session_starts_with_request(self, tmp_path):
        db_path = tmp_path / "test.db"
        # Create a session where slicing would start with ModelResponse
        messages = [
            _make_request("q1"),
            _make_response("a1"),
            _make_request("q2"),
            _make_response("a2"),
            _make_request("q3"),
            _make_response("a3"),
        ]
        with MemoryStore(db_path, dimensions=4) as store:
            store.save_session("s1", "agent-a", messages)
            # max_messages=3 would slice to [response, request, response]
            loaded = store.load_latest_session("agent-a", max_messages=3)
        assert loaded is not None
        # Should skip the leading ModelResponse
        assert isinstance(loaded[0], ModelRequest)

    def test_load_latest_session_empty(self, tmp_path):
        db_path = tmp_path / "test.db"
        with MemoryStore(db_path, dimensions=4) as store:
            loaded = store.load_latest_session("nonexistent")
        assert loaded is None

    def test_prune_sessions(self, tmp_path):
        db_path = tmp_path / "test.db"
        with MemoryStore(db_path, dimensions=4) as store:
            for i in range(5):
                store.save_session(f"s{i}", "agent-a", [_make_request(f"q{i}")])
            deleted = store.prune_sessions("agent-a", keep_count=2)
        assert deleted == 3

    def test_save_session_raises_on_closed_connection(self, tmp_path):
        import sqlite3

        db_path = tmp_path / "test.db"
        store = MemoryStore(db_path, dimensions=4)
        store.close()
        # Writing to a closed connection should now propagate the exception
        with pytest.raises(sqlite3.ProgrammingError):
            store.save_session("s1", "agent-a", [_make_request("hello")])


class TestLongTermMemory:
    def test_add_and_count_memories(self, tmp_path):
        db_path = tmp_path / "test.db"
        with MemoryStore(db_path, dimensions=4) as store:
            store.add_memory("fact 1", "general", [1.0, 0.0, 0.0, 0.0])
            store.add_memory("fact 2", "notes", [0.0, 1.0, 0.0, 0.0])
            assert store.count_memories() == 2

    def test_search_memories_before_any_remember(self, tmp_path):
        """search_memories on a fresh store (no dimensions) returns [] instead of crashing."""
        db_path = tmp_path / "test.db"
        with MemoryStore(db_path) as store:
            results = store.search_memories([1.0, 0.0, 0.0, 0.0], top_k=5)
        assert results == []

    def test_search_memories(self, tmp_path):
        db_path = tmp_path / "test.db"
        with MemoryStore(db_path, dimensions=4) as store:
            store.add_memory("cats are great", "animals", [1.0, 0.0, 0.0, 0.0])
            store.add_memory("dogs are loyal", "animals", [0.0, 1.0, 0.0, 0.0])
            store.add_memory("python is fast", "code", [0.0, 0.0, 1.0, 0.0])
            results = store.search_memories([1.0, 0.0, 0.0, 0.0], top_k=2)
        assert len(results) == 2
        assert results[0][0].content == "cats are great"

    def test_list_memories(self, tmp_path):
        db_path = tmp_path / "test.db"
        with MemoryStore(db_path, dimensions=4) as store:
            store.add_memory("fact 1", "general", [1.0, 0.0, 0.0, 0.0])
            store.add_memory("fact 2", "notes", [0.0, 1.0, 0.0, 0.0])
            store.add_memory("fact 3", "notes", [0.0, 0.0, 1.0, 0.0])
            all_mems = store.list_memories()
            notes_mems = store.list_memories(category="notes")
        assert len(all_mems) == 3
        assert len(notes_mems) == 2

    def test_prune_memories(self, tmp_path):
        db_path = tmp_path / "test.db"
        with MemoryStore(db_path, dimensions=4) as store:
            for i in range(5):
                store.add_memory(f"fact {i}", "general", [float(i == j) for j in range(4)])
            deleted = store.prune_memories(keep_count=2)
            assert deleted == 3
            assert store.count_memories() == 2
            # Verify vec table is also pruned
            vec_count = store._conn.execute("SELECT COUNT(*) FROM memories_vec").fetchone()[0]  # type: ignore[attr-defined]
            assert vec_count == 2


class TestFilterSystemPrompts:
    def test_filters_system_prompt_parts(self):
        messages = [
            _make_system_request("system", "user"),
            _make_response("response"),
        ]
        filtered = _filter_system_prompts(messages)
        assert len(filtered) == 2
        request = filtered[0]
        assert isinstance(request, ModelRequest)
        assert len(request.parts) == 1
        assert isinstance(request.parts[0], UserPromptPart)

    def test_removes_system_only_request(self):
        messages = [
            ModelRequest(parts=[SystemPromptPart(content="system only")]),
            _make_request("real question"),
            _make_response("answer"),
        ]
        filtered = _filter_system_prompts(messages)
        # System-only request should be dropped entirely
        assert len(filtered) == 2

    def test_preserves_non_system_messages(self):
        messages = [_make_request("q1"), _make_response("a1")]
        filtered = _filter_system_prompts(messages)
        assert len(filtered) == 2


class TestConcurrentAccess:
    """Two store instances on the same DB can read/write without errors."""

    def test_concurrent_add_and_search(self, tmp_path):
        import threading

        db_path = tmp_path / "shared.db"
        dims = 4
        emb_a = [1.0, 0.0, 0.0, 0.0]
        emb_b = [0.0, 1.0, 0.0, 0.0]
        errors: list[Exception] = []

        def _writer(label: str, embedding: list[float]) -> None:
            try:
                with MemoryStore(db_path, dimensions=dims) as store:
                    for i in range(10):
                        store.add_memory(f"{label}-{i}", "test", embedding)
            except Exception as exc:
                errors.append(exc)

        t1 = threading.Thread(target=_writer, args=("a", emb_a))
        t2 = threading.Thread(target=_writer, args=("b", emb_b))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert errors == [], f"Concurrent writes failed: {errors}"

        with MemoryStore(db_path, dimensions=dims) as store:
            assert store.count_memories() == 20
            results = store.search_memories(emb_a, top_k=5)
            assert len(results) == 5
