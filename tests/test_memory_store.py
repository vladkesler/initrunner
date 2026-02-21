"""Tests for the memory store."""

from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    SystemPromptPart,
    TextPart,
    UserPromptPart,
)

from initrunner.stores._helpers import _filter_system_prompts
from initrunner.stores.base import MemoryType
from initrunner.stores.zvec_store import ZvecMemoryStore as MemoryStore


def _make_request(content: str) -> ModelRequest:
    return ModelRequest(parts=[UserPromptPart(content=content)])


def _make_response(content: str) -> ModelResponse:
    return ModelResponse(parts=[TextPart(content=content)])


def _make_system_request(system: str, user: str) -> ModelRequest:
    return ModelRequest(parts=[SystemPromptPart(content=system), UserPromptPart(content=user)])


class TestCreateStore:
    def test_create_store(self, tmp_path):
        store_path = tmp_path / "test.zvec"
        with MemoryStore(store_path, dimensions=4):
            assert store_path.exists()

    def test_context_manager(self, tmp_path):
        store_path = tmp_path / "test.zvec"
        with MemoryStore(store_path, dimensions=4) as store:
            store.add_memory("test", "general", [1.0, 0.0, 0.0, 0.0])
        assert store_path.exists()


class TestSessionPersistence:
    def test_save_and_load_session(self, tmp_path):
        store_path = tmp_path / "test.zvec"
        messages = [_make_request("hello"), _make_response("hi")]
        with MemoryStore(store_path, dimensions=4) as store:
            store.save_session("s1", "agent-a", messages)
            loaded = store.load_latest_session("agent-a")
        assert loaded is not None
        assert len(loaded) == 2
        assert isinstance(loaded[0], ModelRequest)
        assert isinstance(loaded[1], ModelResponse)

    def test_save_session_filters_system_prompt(self, tmp_path):
        store_path = tmp_path / "test.zvec"
        messages = [
            _make_system_request("You are helpful", "hello"),
            _make_response("hi"),
        ]
        with MemoryStore(store_path, dimensions=4) as store:
            store.save_session("s1", "agent-a", messages)
            loaded = store.load_latest_session("agent-a")
        assert loaded is not None
        # The system prompt part should be stripped
        request = loaded[0]
        assert isinstance(request, ModelRequest)
        assert len(request.parts) == 1
        assert isinstance(request.parts[0], UserPromptPart)

    def test_load_session_respects_max_messages(self, tmp_path):
        store_path = tmp_path / "test.zvec"
        messages = []
        for i in range(10):
            messages.append(_make_request(f"q{i}"))
            messages.append(_make_response(f"a{i}"))
        with MemoryStore(store_path, dimensions=4) as store:
            store.save_session("s1", "agent-a", messages)
            loaded = store.load_latest_session("agent-a", max_messages=4)
        assert loaded is not None
        assert len(loaded) == 4

    def test_load_session_starts_with_request(self, tmp_path):
        store_path = tmp_path / "test.zvec"
        # Create a session where slicing would start with ModelResponse
        messages = [
            _make_request("q1"),
            _make_response("a1"),
            _make_request("q2"),
            _make_response("a2"),
            _make_request("q3"),
            _make_response("a3"),
        ]
        with MemoryStore(store_path, dimensions=4) as store:
            store.save_session("s1", "agent-a", messages)
            # max_messages=3 would slice to [response, request, response]
            loaded = store.load_latest_session("agent-a", max_messages=3)
        assert loaded is not None
        # Should skip the leading ModelResponse
        assert isinstance(loaded[0], ModelRequest)

    def test_load_latest_session_empty(self, tmp_path):
        store_path = tmp_path / "test.zvec"
        with MemoryStore(store_path, dimensions=4) as store:
            loaded = store.load_latest_session("nonexistent")
        assert loaded is None

    def test_prune_sessions(self, tmp_path):
        store_path = tmp_path / "test.zvec"
        with MemoryStore(store_path, dimensions=4) as store:
            for i in range(5):
                store.save_session(f"s{i}", "agent-a", [_make_request(f"q{i}")])
            deleted = store.prune_sessions("agent-a", keep_count=2)
        assert deleted == 3


class TestLongTermMemory:
    def test_add_and_count_memories(self, tmp_path):
        store_path = tmp_path / "test.zvec"
        with MemoryStore(store_path, dimensions=4) as store:
            store.add_memory("fact 1", "general", [1.0, 0.0, 0.0, 0.0])
            store.add_memory("fact 2", "notes", [0.0, 1.0, 0.0, 0.0])
            assert store.count_memories() == 2

    def test_search_memories_before_any_remember(self, tmp_path):
        """search_memories on a fresh store (no dimensions) returns [] instead of crashing."""
        store_path = tmp_path / "test.zvec"
        with MemoryStore(store_path) as store:
            results = store.search_memories([1.0, 0.0, 0.0, 0.0], top_k=5)
        assert results == []

    def test_search_memories(self, tmp_path):
        store_path = tmp_path / "test.zvec"
        with MemoryStore(store_path, dimensions=4) as store:
            store.add_memory("cats are great", "animals", [1.0, 0.0, 0.0, 0.0])
            store.add_memory("dogs are loyal", "animals", [0.0, 1.0, 0.0, 0.0])
            store.add_memory("python is fast", "code", [0.0, 0.0, 1.0, 0.0])
            results = store.search_memories([1.0, 0.0, 0.0, 0.0], top_k=2)
        assert len(results) == 2
        assert results[0][0].content == "cats are great"

    def test_list_memories(self, tmp_path):
        store_path = tmp_path / "test.zvec"
        with MemoryStore(store_path, dimensions=4) as store:
            store.add_memory("fact 1", "general", [1.0, 0.0, 0.0, 0.0])
            store.add_memory("fact 2", "notes", [0.0, 1.0, 0.0, 0.0])
            store.add_memory("fact 3", "notes", [0.0, 0.0, 1.0, 0.0])
            all_mems = store.list_memories()
            notes_mems = store.list_memories(category="notes")
        assert len(all_mems) == 3
        assert len(notes_mems) == 2

    def test_prune_memories(self, tmp_path):
        store_path = tmp_path / "test.zvec"
        with MemoryStore(store_path, dimensions=4) as store:
            for i in range(5):
                store.add_memory(f"fact {i}", "general", [float(i == j) for j in range(4)])
            deleted = store.prune_memories(keep_count=2)
            assert deleted == 3
            assert store.count_memories() == 2


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
    """Concurrent threads sharing one store instance can read/write without errors."""

    def test_concurrent_add_and_search(self, tmp_path):
        import threading

        store_path = tmp_path / "shared.zvec"
        dims = 4
        emb_a = [1.0, 0.0, 0.0, 0.0]
        emb_b = [0.0, 1.0, 0.0, 0.0]
        errors: list[Exception] = []

        with MemoryStore(store_path, dimensions=dims) as store:

            def _writer(label: str, embedding: list[float]) -> None:
                try:
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
            assert store.count_memories() == 20
            results = store.search_memories(emb_a, top_k=5)
            assert len(results) == 5


class TestMemoryTypes:
    def test_add_and_count_by_type(self, tmp_path):
        store_path = tmp_path / "test.zvec"
        with MemoryStore(store_path, dimensions=4) as store:
            store.add_memory(
                "fact", "general", [1.0, 0.0, 0.0, 0.0], memory_type=MemoryType.SEMANTIC
            )
            store.add_memory(
                "episode", "run", [0.0, 1.0, 0.0, 0.0], memory_type=MemoryType.EPISODIC
            )
            store.add_memory(
                "procedure", "policy", [0.0, 0.0, 1.0, 0.0], memory_type=MemoryType.PROCEDURAL
            )
            assert store.count_memories() == 3
            assert store.count_memories(memory_type=MemoryType.SEMANTIC) == 1
            assert store.count_memories(memory_type=MemoryType.EPISODIC) == 1
            assert store.count_memories(memory_type=MemoryType.PROCEDURAL) == 1

    def test_list_by_type(self, tmp_path):
        store_path = tmp_path / "test.zvec"
        with MemoryStore(store_path, dimensions=4) as store:
            store.add_memory(
                "fact", "general", [1.0, 0.0, 0.0, 0.0], memory_type=MemoryType.SEMANTIC
            )
            store.add_memory(
                "episode", "run", [0.0, 1.0, 0.0, 0.0], memory_type=MemoryType.EPISODIC
            )
            store.add_memory(
                "procedure", "policy", [0.0, 0.0, 1.0, 0.0], memory_type=MemoryType.PROCEDURAL
            )
            semantic = store.list_memories(memory_type=MemoryType.SEMANTIC)
            assert len(semantic) == 1
            assert semantic[0].memory_type == MemoryType.SEMANTIC
            episodic = store.list_memories(memory_type=MemoryType.EPISODIC)
            assert len(episodic) == 1
            assert episodic[0].memory_type == MemoryType.EPISODIC

    def test_prune_by_type(self, tmp_path):
        store_path = tmp_path / "test.zvec"
        with MemoryStore(store_path, dimensions=4) as store:
            for i in range(5):
                store.add_memory(
                    f"episode {i}",
                    "run",
                    [float(i == j) for j in range(4)],
                    memory_type=MemoryType.EPISODIC,
                )
            store.add_memory(
                "fact", "general", [0.5, 0.5, 0.0, 0.0], memory_type=MemoryType.SEMANTIC
            )

            deleted = store.prune_memories(keep_count=2, memory_type=MemoryType.EPISODIC)
            assert deleted == 3
            # Semantic memory should be untouched
            assert store.count_memories(memory_type=MemoryType.SEMANTIC) == 1
            assert store.count_memories(memory_type=MemoryType.EPISODIC) == 2

    def test_search_with_type_filter(self, tmp_path):
        store_path = tmp_path / "test.zvec"
        with MemoryStore(store_path, dimensions=4) as store:
            store.add_memory(
                "semantic fact", "general", [1.0, 0.0, 0.0, 0.0], memory_type=MemoryType.SEMANTIC
            )
            store.add_memory(
                "episode event", "run", [0.9, 0.1, 0.0, 0.0], memory_type=MemoryType.EPISODIC
            )
            store.add_memory(
                "procedure rule", "policy", [0.8, 0.2, 0.0, 0.0], memory_type=MemoryType.PROCEDURAL
            )

            # Search for only episodic memories
            results = store.search_memories(
                [1.0, 0.0, 0.0, 0.0], top_k=5, memory_types=[MemoryType.EPISODIC]
            )
            assert len(results) == 1
            assert results[0][0].memory_type == MemoryType.EPISODIC

            # Search for semantic + procedural
            results = store.search_memories(
                [1.0, 0.0, 0.0, 0.0],
                top_k=5,
                memory_types=[MemoryType.SEMANTIC, MemoryType.PROCEDURAL],
            )
            assert len(results) == 2
            types = {r[0].memory_type for r in results}
            assert types == {MemoryType.SEMANTIC, MemoryType.PROCEDURAL}

    def test_default_memory_type_is_semantic(self, tmp_path):
        store_path = tmp_path / "test.zvec"
        with MemoryStore(store_path, dimensions=4) as store:
            store.add_memory("plain memory", "general", [1.0, 0.0, 0.0, 0.0])
            mems = store.list_memories()
            assert mems[0].memory_type == MemoryType.SEMANTIC

    def test_metadata_storage(self, tmp_path):
        store_path = tmp_path / "test.zvec"
        with MemoryStore(store_path, dimensions=4) as store:
            meta = {"tool_calls": 3, "duration_ms": 1200}
            store.add_memory(
                "episode",
                "run",
                [1.0, 0.0, 0.0, 0.0],
                memory_type=MemoryType.EPISODIC,
                metadata=meta,
            )
            mems = store.list_memories()
            assert mems[0].metadata == meta

    def test_metadata_none(self, tmp_path):
        store_path = tmp_path / "test.zvec"
        with MemoryStore(store_path, dimensions=4) as store:
            store.add_memory("fact", "general", [1.0, 0.0, 0.0, 0.0])
            mems = store.list_memories()
            assert mems[0].metadata is None


class TestConsolidation:
    def test_mark_consolidated(self, tmp_path):
        store_path = tmp_path / "test.zvec"
        with MemoryStore(store_path, dimensions=4) as store:
            id1 = store.add_memory(
                "ep1", "run", [1.0, 0.0, 0.0, 0.0], memory_type=MemoryType.EPISODIC
            )
            id2 = store.add_memory(
                "ep2", "run", [0.0, 1.0, 0.0, 0.0], memory_type=MemoryType.EPISODIC
            )

            store.mark_consolidated([id1, id2], "2026-01-01T00:00:00+00:00")

            mems = store.list_memories(memory_type=MemoryType.EPISODIC)
            for m in mems:
                assert m.consolidated_at == "2026-01-01T00:00:00+00:00"

    def test_get_unconsolidated_episodes(self, tmp_path):
        store_path = tmp_path / "test.zvec"
        with MemoryStore(store_path, dimensions=4) as store:
            id1 = store.add_memory(
                "ep1", "run", [1.0, 0.0, 0.0, 0.0], memory_type=MemoryType.EPISODIC
            )
            store.add_memory("ep2", "run", [0.0, 1.0, 0.0, 0.0], memory_type=MemoryType.EPISODIC)
            store.add_memory(
                "fact", "general", [0.0, 0.0, 1.0, 0.0], memory_type=MemoryType.SEMANTIC
            )

            # Mark one as consolidated
            store.mark_consolidated([id1], "2026-01-01T00:00:00+00:00")

            unconsolidated = store.get_unconsolidated_episodes()
            assert len(unconsolidated) == 1
            assert unconsolidated[0].content == "ep2"

    def test_get_unconsolidated_episodes_respects_limit(self, tmp_path):
        store_path = tmp_path / "test.zvec"
        with MemoryStore(store_path, dimensions=4) as store:
            for i in range(10):
                store.add_memory(
                    f"ep{i}",
                    "run",
                    [float(i == j) for j in range(4)],
                    memory_type=MemoryType.EPISODIC,
                )

            unconsolidated = store.get_unconsolidated_episodes(limit=3)
            assert len(unconsolidated) == 3

    def test_mark_consolidated_empty_list(self, tmp_path):
        store_path = tmp_path / "test.zvec"
        with MemoryStore(store_path, dimensions=4) as store:
            # Should not error
            store.mark_consolidated([], "2026-01-01T00:00:00+00:00")
