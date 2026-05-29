"""Tests for the in-process local (fastembed) embedding provider."""

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from initrunner.ingestion.embeddings import (
    _DEFAULT_MODELS,
    LocalEmbeddingModel,
    compute_model_identity,
    create_embedder,
    embed_texts,
)

DEFAULT_LOCAL_MODEL = "BAAI/bge-small-en-v1.5"


# ---------------------------------------------------------------------------
# Unit tests (no fastembed install required)
# ---------------------------------------------------------------------------


class TestLocalProviderRouting:
    def test_default_models_has_local(self):
        assert _DEFAULT_MODELS["local"] == "local:BAAI/bge-small-en-v1.5"

    def test_create_embedder_local_uses_local_model(self):
        """create_embedder('local') wraps a LocalEmbeddingModel with the default model."""
        with patch("initrunner.ingestion.embeddings.LocalEmbeddingModel") as mock_model_cls:
            create_embedder(provider="local")
            mock_model_cls.assert_called_once_with(DEFAULT_LOCAL_MODEL)

    def test_create_embedder_local_custom_model(self):
        """A bare model name is forwarded unchanged."""
        with patch("initrunner.ingestion.embeddings.LocalEmbeddingModel") as mock_model_cls:
            create_embedder(provider="local", model="BAAI/bge-base-en-v1.5")
            mock_model_cls.assert_called_once_with("BAAI/bge-base-en-v1.5")

    def test_create_embedder_local_strips_prefix(self):
        """A ``local:`` prefix is stripped before reaching fastembed."""
        with patch("initrunner.ingestion.embeddings.LocalEmbeddingModel") as mock_model_cls:
            create_embedder(provider="local", model="local:BAAI/bge-base-en-v1.5")
            mock_model_cls.assert_called_once_with("BAAI/bge-base-en-v1.5")

    def test_create_embedder_local_ignores_base_url(self):
        """Local is distinct from ollama and never routes through an HTTP provider."""
        with (
            patch("initrunner.ingestion.embeddings.LocalEmbeddingModel") as mock_model_cls,
            patch("initrunner.ingestion.embeddings._create_custom_embedder") as mock_custom,
        ):
            create_embedder(provider="local", base_url="http://localhost:1234/v1")
            mock_model_cls.assert_called_once_with(DEFAULT_LOCAL_MODEL)
            mock_custom.assert_not_called()


class TestComputeModelIdentityLocal:
    def test_local_default_no_hash(self):
        assert compute_model_identity("local", "") == "local:BAAI/bge-small-en-v1.5"

    def test_local_custom_model(self):
        assert (
            compute_model_identity("local", "BAAI/bge-base-en-v1.5")
            == "local:BAAI/bge-base-en-v1.5"
        )

    def test_local_already_prefixed(self):
        assert (
            compute_model_identity("local", "local:BAAI/bge-small-en-v1.5")
            == "local:BAAI/bge-small-en-v1.5"
        )

    def test_local_has_no_url_hash(self):
        """Local identities are provider:model only, never a base_url hash."""
        result = compute_model_identity("local", "BAAI/bge-base-en-v1.5")
        assert len(result.split(":")) == 2


class TestRequireEmbeddingsLocal:
    def test_missing_fastembed_raises_missing_extra(self):
        """When fastembed is absent, instantiation raises MissingExtraError with a hint."""
        from initrunner._compat import MissingExtraError

        with patch(
            "initrunner._compat.importlib.import_module",
            side_effect=ImportError("no fastembed"),
        ):
            with pytest.raises(MissingExtraError, match=r"local-embeddings"):
                LocalEmbeddingModel(DEFAULT_LOCAL_MODEL)


class TestLocalEmbeddingModelLazyLoad:
    def test_lazy_load_not_called_at_init(self):
        """Constructing the model must not load the underlying fastembed model."""
        with patch("initrunner._compat.require_embeddings_local"):
            model = LocalEmbeddingModel(DEFAULT_LOCAL_MODEL)
            assert model._model is None
            assert model.model_name == DEFAULT_LOCAL_MODEL
            assert model.system == "local"
            assert model.base_url is None

    def test_embed_loads_model_once_and_uses_query_path(self):
        """``embed`` lazily loads the model and dispatches query vs document paths."""
        fake_array = MagicMock()
        fake_array.tolist.return_value = [0.1, 0.2, 0.3]
        fake_fastembed = MagicMock()
        fake_fastembed.query_embed.return_value = iter([fake_array])
        fake_fastembed.passage_embed.return_value = iter([fake_array])

        with patch("initrunner._compat.require_embeddings_local"):
            model = LocalEmbeddingModel(DEFAULT_LOCAL_MODEL)

        with patch.object(model, "_load", return_value=fake_fastembed) as mock_load:
            result = asyncio.run(model.embed("a query", input_type="query"))

        mock_load.assert_called_once()
        fake_fastembed.query_embed.assert_called_once_with(["a query"])
        fake_fastembed.passage_embed.assert_not_called()
        assert result.embeddings == [[0.1, 0.2, 0.3]]
        assert result.input_type == "query"
        assert result.provider_name == "local"
        assert result.model_name == DEFAULT_LOCAL_MODEL

    def test_embed_document_uses_passage_path(self):
        fake_array = MagicMock()
        fake_array.tolist.return_value = [1.0, 2.0]
        fake_fastembed = MagicMock()
        fake_fastembed.passage_embed.return_value = iter([fake_array, fake_array])

        with patch("initrunner._compat.require_embeddings_local"):
            model = LocalEmbeddingModel(DEFAULT_LOCAL_MODEL)

        with patch.object(model, "_load", return_value=fake_fastembed):
            result = asyncio.run(model.embed(["doc one", "doc two"], input_type="document"))

        fake_fastembed.passage_embed.assert_called_once_with(["doc one", "doc two"])
        fake_fastembed.query_embed.assert_not_called()
        assert len(result.embeddings) == 2


# ---------------------------------------------------------------------------
# Integration tests (require the local-embeddings extra)
# ---------------------------------------------------------------------------


class TestLocalEmbedderFunctional:
    def test_embed_default_model_dimension(self):
        pytest.importorskip("fastembed")
        embedder = create_embedder(provider="local")
        vectors = asyncio.run(embed_texts(embedder, ["sample text"], input_type="document"))
        assert len(vectors) == 1
        assert len(vectors[0]) == 384
        assert all(isinstance(x, float) for x in vectors[0])

    def test_embed_consistent_dimensions(self):
        pytest.importorskip("fastembed")
        embedder = create_embedder(provider="local")
        vectors = asyncio.run(
            embed_texts(
                embedder,
                ["first text", "an entirely different second one"],
                input_type="document",
            )
        )
        assert len(vectors) == 2
        assert len({len(v) for v in vectors}) == 1

    def test_query_and_document_same_dimension(self):
        pytest.importorskip("fastembed")
        embedder = create_embedder(provider="local")
        doc = asyncio.run(embed_texts(embedder, ["a document"], input_type="document"))
        query = asyncio.run(embed_texts(embedder, ["a query"], input_type="query"))
        assert len(doc[0]) == len(query[0])

    def test_custom_model_dimension(self):
        pytest.importorskip("fastembed")
        embedder = create_embedder(provider="local", model="BAAI/bge-base-en-v1.5")
        vectors = asyncio.run(embed_texts(embedder, ["sample"], input_type="document"))
        assert len(vectors[0]) == 768


class TestMemoryStoreWithLocalEmbedder:
    def test_add_and_search_with_local_embedder(self, tmp_path):
        pytest.importorskip("fastembed")
        from initrunner.stores.lance_store import LanceMemoryStore

        embedder = create_embedder(provider="local")
        store_path = tmp_path / "mem.lance"
        with LanceMemoryStore(store_path) as store:
            content = "the capital of France is Paris"
            vec = asyncio.run(embed_texts(embedder, [content], input_type="document"))[0]
            store.add_memory(content, "geography", vec)
            assert store.dimensions == 384

            query_vec = asyncio.run(
                embed_texts(embedder, ["which city is the French capital"], input_type="query")
            )[0]
            results = store.search_memories(query_vec, top_k=1)
            assert len(results) == 1
            assert results[0][0].content == content

    def test_dimension_mismatch_on_model_switch(self, tmp_path):
        """A store fixed at one dimension cannot be reused with a different-dimension model.

        The canonical guard fires when reopening the store with an explicit,
        mismatched ``dimensions``: a 384d store rejects ``dimensions=768``.
        Attempting to add a 768d vector to the same 384d store also fails, since
        the vector column has a fixed size.
        """
        pytest.importorskip("fastembed")
        from initrunner.stores.base import DimensionMismatchError
        from initrunner.stores.lance_store import LanceMemoryStore

        small = create_embedder(provider="local", model="BAAI/bge-small-en-v1.5")
        big = create_embedder(provider="local", model="BAAI/bge-base-en-v1.5")
        store_path = tmp_path / "mem.lance"

        with LanceMemoryStore(store_path) as store:
            small_vec = asyncio.run(embed_texts(small, ["small"], input_type="document"))[0]
            store.add_memory("small", "c", small_vec)
            assert store.dimensions == 384

        # Reopening at a different dimension is rejected up front.
        with pytest.raises(DimensionMismatchError, match=r"384d.*768d"):
            LanceMemoryStore(store_path, dimensions=768)

        # Adding a 768d vector to the 384d store is rejected by the fixed-size column.
        with LanceMemoryStore(store_path) as store:
            big_vec = asyncio.run(embed_texts(big, ["big"], input_type="document"))[0]
            with pytest.raises(Exception):  # noqa: B017 - lancedb raises a low-level RuntimeError
                store.add_memory("big", "c", big_vec)
