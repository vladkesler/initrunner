"""Embedder factory wrapping PydanticAI's Embedder."""

from __future__ import annotations

import hashlib
import os
from typing import Literal, cast

from pydantic_ai.embeddings import Embedder

_DEFAULT_MODELS: dict[str, str] = {
    "openai": "openai:text-embedding-3-small",
    "anthropic": "openai:text-embedding-3-small",  # Anthropic has no embeddings; use OpenAI
    "google": "google:text-embedding-004",
    "ollama": "ollama:nomic-embed-text",
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
    value = os.environ.get(env_var)
    if value:
        return value
    hint = (
        f"Embedding API key not found: set the {env_var} environment variable.\n"
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
    """
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
        resolved_url = base_url or "http://localhost:11434/v1"
        api_key = "ollama"
        default_model = _DEFAULT_MODELS.get("ollama", "ollama:nomic-embed-text")
    else:
        resolved_url = base_url
        if api_key_env:
            api_key = os.environ.get(api_key_env)
            if not api_key:
                raise ValueError(
                    f"api_key_env '{api_key_env}' is set but the environment "
                    "variable is missing or empty"
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
    import asyncio

    embedder = create_embedder(provider, model, base_url=base_url, api_key_env=api_key_env)
    coro = embed_texts(embedder, [text], input_type=input_type)

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop is not None and loop.is_running():
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            vectors = cast(list[list[float]], pool.submit(asyncio.run, coro).result())
            return vectors[0]
    return asyncio.run(coro)[0]


async def embed_texts(
    embedder: Embedder,
    texts: list[str],
    *,
    input_type: Literal["query", "document"] = "document",
) -> list[list[float]]:
    """Embed a list of texts, returning float vectors."""
    result = await embedder.embed(texts, input_type=input_type)
    return [list(v) for v in result.embeddings]
