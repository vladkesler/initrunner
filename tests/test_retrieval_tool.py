"""Tests for the auto-retrieval tool (search_documents)."""

from unittest.mock import patch

from initrunner.agent.tools.retrieval import build_retrieval_toolset
from initrunner.stores.base import StoreConfig
from initrunner.stores.lance_store import LanceDocumentStore


def _seed_store(db_path):
    with LanceDocumentStore(db_path, dimensions=4) as store:
        store.add_documents(
            texts=[
                "python programming language",
                "machine learning models",
                "data science with python",
            ],
            embeddings=[
                [1.0, 0.0, 0.0, 0.0],
                [0.0, 1.0, 0.0, 0.0],
                [0.0, 0.0, 1.0, 0.0],
            ],
            sources=["a.md", "b.md", "c.md"],
        )


def _store_config(db_path, **overrides):
    base: dict[str, object] = {
        "db_path": db_path,
        "embed_provider": "openai",
        "embed_model": "text-embedding-3-small",
    }
    base.update(overrides)
    return StoreConfig(**base)  # type: ignore[invalid-argument-type]


def _call(toolset, **kwargs):
    fn = toolset.tools["search_documents"].function
    return fn(**kwargs)


class TestSearchDocumentsTool:
    def test_vector_strategy_default(self, tmp_path):
        db_path = tmp_path / "store.lance"
        _seed_store(db_path)
        toolset = build_retrieval_toolset(_store_config(db_path))
        with patch(
            "initrunner.agent.tools.retrieval._embed_single",
            return_value=[1.0, 0.0, 0.0, 0.0],
        ):
            out = _call(toolset, query="python", top_k=2)
        assert "a.md" in out
        assert "Score:" in out

    def test_hybrid_strategy_param(self, tmp_path):
        db_path = tmp_path / "store.lance"
        _seed_store(db_path)
        toolset = build_retrieval_toolset(_store_config(db_path))
        with patch(
            "initrunner.agent.tools.retrieval._embed_single",
            return_value=[1.0, 0.0, 0.0, 0.0],
        ):
            out = _call(toolset, query="python", top_k=3, strategy="hybrid")
        assert "Source:" in out
        assert "a.md" in out

    def test_role_default_strategy_used(self, tmp_path):
        db_path = tmp_path / "store.lance"
        _seed_store(db_path)
        toolset = build_retrieval_toolset(_store_config(db_path, retrieval_strategy="hybrid"))
        captured = {}

        real_hybrid = LanceDocumentStore.hybrid_search

        def spy(self, *args, **kwargs):
            captured["strategy"] = kwargs.get("retrieval_strategy")
            return real_hybrid(self, *args, **kwargs)

        with (
            patch(
                "initrunner.agent.tools.retrieval._embed_single",
                return_value=[1.0, 0.0, 0.0, 0.0],
            ),
            patch.object(LanceDocumentStore, "hybrid_search", spy),
        ):
            out = _call(toolset, query="python")
        assert captured["strategy"] == "hybrid"
        assert "a.md" in out

    def test_explicit_strategy_overrides_default(self, tmp_path):
        db_path = tmp_path / "store.lance"
        _seed_store(db_path)
        toolset = build_retrieval_toolset(_store_config(db_path, retrieval_strategy="hybrid"))
        with (
            patch(
                "initrunner.agent.tools.retrieval._embed_single",
                return_value=[1.0, 0.0, 0.0, 0.0],
            ),
            patch.object(LanceDocumentStore, "hybrid_search", autospec=True) as hybrid_spy,
        ):
            _call(toolset, query="python", strategy="vector")
        hybrid_spy.assert_not_called()

    def test_no_store_yet(self, tmp_path):
        db_path = tmp_path / "missing.lance"
        toolset = build_retrieval_toolset(_store_config(db_path))
        out = _call(toolset, query="python")
        assert "No documents have been ingested" in out

    def test_no_results(self, tmp_path):
        db_path = tmp_path / "store.lance"
        with LanceDocumentStore(db_path, dimensions=4):
            pass
        toolset = build_retrieval_toolset(_store_config(db_path))
        with patch(
            "initrunner.agent.tools.retrieval._embed_single",
            return_value=[1.0, 0.0, 0.0, 0.0],
        ):
            out = _call(toolset, query="python", strategy="hybrid")
        assert "No relevant documents found" in out
