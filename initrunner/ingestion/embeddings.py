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

    if model:
        model_str = model if ":" in model else f"{provider}:{model}"
    else:
        model_str = _DEFAULT_MODELS.get(provider, "openai:text-embedding-3-small")
    return Embedder(model_str)


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
