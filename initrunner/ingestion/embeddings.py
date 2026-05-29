"""Embedder factory wrapping PydanticAI's Embedder.

Dimension consistency: a store or index is created with the embedding dimension
of whichever model first wrote to it, and that dimension is then fixed. Querying
or extending such a store with an embedder that produces a different number of
dimensions raises ``DimensionMismatchError``. Switching embedding models (for
example ``local:BAAI/bge-small-en-v1.5`` at 384 dims to
``local:BAAI/bge-base-en-v1.5`` at 768 dims, or between ``local`` and an HTTP
provider) requires a fresh store path.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from typing import TYPE_CHECKING, Literal

from pydantic_ai.embeddings import Embedder, EmbeddingModel

if TYPE_CHECKING:
    from pydantic_ai.embeddings import EmbeddingResult
    from pydantic_ai.embeddings.settings import EmbeddingSettings

_DEFAULT_MODELS: dict[str, str] = {
    "openai": "openai:text-embedding-3-small",
    "anthropic": "openai:text-embedding-3-small",  # Anthropic has no embeddings; use OpenAI
    "google": "google:text-embedding-004",
    "ollama": "ollama:nomic-embed-text",
    "local": "local:BAAI/bge-small-en-v1.5",
}

_PROVIDER_EMBEDDING_KEY_DEFAULTS: dict[str, str] = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "OPENAI_API_KEY",
    "google": "GOOGLE_API_KEY",
}


def _default_embedding_key_env(provider: str) -> str:
    """Return the default environment variable name for embedding API keys."""
    return _PROVIDER_EMBEDDING_KEY_DEFAULTS.get(provider, "OPENAI_API_KEY")


def _require_embedding_key(env_var: str, provider: str) -> str:
    """Validate that *env_var* is set and return its value.

    Raises a clear ``ValueError`` when the key is missing, explaining that
    embedding keys may differ from LLM keys.
    """
    from initrunner.credentials import get_resolver

    value = get_resolver().get(env_var)
    if value:
        return value
    hint = (
        f"Embedding API key not found: set the {env_var} environment variable "
        f"or run: initrunner vault set {env_var}\n"
        f"Note: embedding keys may differ from LLM keys"
    )
    if provider == "anthropic":
        hint += " (Anthropic has no embeddings API; OpenAI is used by default)"
    hint += (
        ".\nYou can override the key variable with "
        "ingest.embeddings.api_key_env or memory.embeddings.api_key_env in your role.yaml."
    )
    raise ValueError(hint)


def create_embedder(
    provider: str = "", model: str = "", base_url: str = "", api_key_env: str = ""
) -> Embedder:
    """Create a PydanticAI Embedder from provider/model hints.

    If *model* is given, it's used directly (e.g. "openai:text-embedding-3-large").
    Otherwise the default for *provider* is chosen.
    Falls back to OpenAI's text-embedding-3-small.

    For Ollama or custom endpoints, *base_url* triggers OpenAI-compatible provider setup.

    The ``local`` provider runs an in-process embedding model via fastembed with
    no HTTP hop. It is distinct from ``ollama``, which routes through an
    OpenAI-compatible HTTP client and needs a running endpoint.
    """
    if provider == "local":
        return _create_local_embedder(model)

    if provider == "ollama" or base_url:
        return _create_custom_embedder(provider, model, base_url, api_key_env=api_key_env)

    # Resolve model string and provider prefix
    if model:
        model_str = model if ":" in model else f"{provider}:{model}"
    else:
        model_str = _DEFAULT_MODELS.get(provider, "openai:text-embedding-3-small")

    resolved_provider = model_str.split(":")[0] if ":" in model_str else provider

    # For standard providers, validate and inject the embedding API key
    if resolved_provider in _PROVIDER_EMBEDDING_KEY_DEFAULTS or api_key_env:
        key_env = api_key_env or _default_embedding_key_env(resolved_provider)
        api_key = _require_embedding_key(key_env, provider or resolved_provider)
        return _create_standard_embedder(resolved_provider, model_str, api_key)

    return Embedder(model_str)


def _create_standard_embedder(resolved_provider: str, model_str: str, api_key: str) -> Embedder:
    """Build an Embedder for a standard provider with an explicit API key."""
    model_name = model_str.split(":", 1)[-1] if ":" in model_str else model_str

    if resolved_provider == "google":
        from pydantic_ai.embeddings.google import GoogleEmbeddingModel
        from pydantic_ai.providers.google import GoogleProvider

        embed_model = GoogleEmbeddingModel(model_name, provider=GoogleProvider(api_key=api_key))
        return Embedder(embed_model)

    # OpenAI-family (covers openai, anthropic default, and others)
    from pydantic_ai.embeddings.openai import OpenAIEmbeddingModel
    from pydantic_ai.providers.openai import OpenAIProvider

    embed_model = OpenAIEmbeddingModel(model_name, provider=OpenAIProvider(api_key=api_key))
    return Embedder(embed_model)


def _create_custom_embedder(
    provider: str, model: str, base_url: str, *, api_key_env: str = ""
) -> Embedder:
    """Create an Embedder for Ollama or custom OpenAI-compatible endpoints."""
    from pydantic_ai.providers.openai import OpenAIProvider

    if provider == "ollama":
        from initrunner.services.providers import OLLAMA_DEFAULT_BASE_URL

        resolved_url = base_url or OLLAMA_DEFAULT_BASE_URL
        api_key = "ollama"
        default_model = _DEFAULT_MODELS.get("ollama", "ollama:nomic-embed-text")
    else:
        resolved_url = base_url
        if api_key_env:
            from initrunner.credentials import get_resolver

            api_key = get_resolver().get(api_key_env)
            if not api_key:
                raise ValueError(
                    f"api_key_env '{api_key_env}' is set but no value found "
                    f"(tried env and vault). Run: initrunner vault set {api_key_env}"
                )
        else:
            api_key = "custom-provider"
        default_model = _DEFAULT_MODELS.get(provider, "openai:text-embedding-3-small")

    if model:
        # Strip provider prefix if present (e.g. "ollama:nomic-embed-text" -> "nomic-embed-text")
        model_name = model.split(":", 1)[-1] if ":" in model else model
    else:
        model_name = default_model.split(":", 1)[-1] if ":" in default_model else default_model

    openai_provider = OpenAIProvider(base_url=resolved_url, api_key=api_key)
    return Embedder("openai:" + model_name, provider=openai_provider)  # type: ignore[call-arg]


class LocalEmbeddingModel(EmbeddingModel):
    """In-process embedding model backed by fastembed.

    Runs entirely on the local machine with no HTTP hop, which suits offline or
    air-gapped environments and avoids per-call API costs. The underlying
    fastembed model is downloaded from Hugging Face on first use and cached on
    disk; subsequent runs load it from the cache.

    The model is loaded lazily on the first ``embed`` call so that constructing
    the embedder stays cheap when it is never exercised. Query and document
    inputs use fastembed's dedicated ``query_embed`` and ``passage_embed`` paths.
    """

    def __init__(
        self,
        model_name: str,
        *,
        settings: EmbeddingSettings | None = None,
    ) -> None:
        from initrunner._compat import require_embeddings_local

        require_embeddings_local()
        super().__init__(settings=settings)
        self._model_name = model_name
        self._model = None

    @property
    def model_name(self) -> str:
        """The fastembed model name (for example ``BAAI/bge-small-en-v1.5``)."""
        return self._model_name

    @property
    def system(self) -> str:
        """The provider/system identifier."""
        return "local"

    @property
    def base_url(self) -> str | None:
        """No base URL: this model runs in-process."""
        return None

    def _load(self):
        from fastembed import TextEmbedding  # type: ignore[import-not-found]

        if self._model is None:
            self._model = TextEmbedding(model_name=self._model_name)
        return self._model

    def _embed_sync(self, inputs: list[str], input_type: str) -> list[list[float]]:
        model = self._load()
        embed_fn = model.query_embed if input_type == "query" else model.passage_embed
        return [vector.tolist() for vector in embed_fn(inputs)]

    async def embed(
        self,
        inputs: str | Sequence[str],
        *,
        input_type: Literal["query", "document"] = "document",
        settings: EmbeddingSettings | None = None,
    ) -> EmbeddingResult:
        from pydantic_ai import _utils
        from pydantic_ai.embeddings import EmbeddingResult

        texts = [inputs] if isinstance(inputs, str) else list(inputs)
        embeddings = await _utils.run_in_executor(self._embed_sync, texts, input_type)
        return EmbeddingResult(
            embeddings=embeddings,
            inputs=texts,
            input_type=input_type,
            model_name=self.model_name,
            provider_name=self.system,
        )


def _create_local_embedder(model: str) -> Embedder:
    """Create an in-process Embedder using fastembed.

    *model* may carry the ``local:`` prefix (for example ``local:BAAI/bge-base-en-v1.5``)
    or be a bare fastembed model name. When empty, the default
    ``BAAI/bge-small-en-v1.5`` (384 dimensions) is used.
    """
    if model:
        model_name = model.split(":", 1)[-1] if ":" in model else model
    else:
        model_name = _DEFAULT_MODELS["local"].split(":", 1)[-1]
    return Embedder(LocalEmbeddingModel(model_name))


def compute_model_identity(provider: str, model: str, base_url: str = "") -> str:
    """Return a stable identity string for an embedding provider/model combination.

    Standard providers: ``"{provider}:{model}"``
    Custom endpoints (with *base_url*): ``"{provider}:{model}:{url_hash}"``
    where *url_hash* is the first 8 chars of the SHA-256 of *base_url*.
    """
    resolved_model = model or _DEFAULT_MODELS.get(provider, "openai:text-embedding-3-small")
    # Normalise: if model already has a provider prefix, use as-is; otherwise prepend provider
    if ":" not in resolved_model:
        resolved_model = f"{provider}:{resolved_model}"
    if base_url:
        url_hash = hashlib.sha256(base_url.encode()).hexdigest()[:8]
        return f"{resolved_model}:{url_hash}"
    return resolved_model


def embed_single(
    provider: str,
    model: str,
    text: str,
    *,
    base_url: str = "",
    api_key_env: str = "",
    input_type: Literal["query", "document"] = "query",
) -> list[float]:
    """Create an embedder and embed a single text synchronously."""
    from initrunner._async import run_sync

    embedder = create_embedder(provider, model, base_url=base_url, api_key_env=api_key_env)
    coro = embed_texts(embedder, [text], input_type=input_type)
    vectors = run_sync(coro)
    return vectors[0]


async def embed_texts(
    embedder: Embedder,
    texts: list[str],
    *,
    input_type: Literal["query", "document"] = "document",
) -> list[list[float]]:
    """Embed a list of texts, returning float vectors."""
    result = await embedder.embed(texts, input_type=input_type)
    return [list(v) for v in result.embeddings]


async def embed_single_async(
    provider: str,
    model: str,
    text: str,
    *,
    base_url: str = "",
    api_key_env: str = "",
    input_type: Literal["query", "document"] = "query",
) -> list[float]:
    """Async variant of ``embed_single`` — directly awaits ``embed_texts``."""
    embedder = create_embedder(provider, model, base_url=base_url, api_key_env=api_key_env)
    vectors = await embed_texts(embedder, [text], input_type=input_type)
    return vectors[0]


def get_reranker(reranker_type: str = "rrf", model: str = ""):
    """Build a lancedb reranker for hybrid retrieval.

    ``rrf`` returns a reciprocal rank fusion reranker, which combines vector and
    full-text rankings without any extra dependency. ``cross_encoder`` returns a
    cross-encoder reranker, which requires the optional ``sentence-transformers``
    (and ``torch``) backend; when that backend is missing this raises
    :class:`MissingExtraError` so callers can degrade explicitly.
    """
    from lancedb.rerankers import RRFReranker  # type: ignore[import-not-found]

    if reranker_type == "rrf":
        return RRFReranker()
    if reranker_type == "cross_encoder":
        from lancedb.rerankers import CrossEncoderReranker  # type: ignore[import-not-found]

        from initrunner._compat import MissingExtraError

        model_name = model or "cross-encoder/ms-marco-MiniLM-L-6-v2"
        try:
            return CrossEncoderReranker(model_name=model_name)
        except ImportError as exc:
            raise MissingExtraError(
                "'sentence-transformers' is required for cross-encoder reranking: "
                "uv pip install sentence-transformers"
            ) from exc
    raise ValueError(f"Unknown reranker_type: {reranker_type!r}")
