"""Web scraper tool: fetch, chunk, embed, and store web pages."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from urllib.parse import urlparse

from pydantic_ai.toolsets.function import FunctionToolset

from initrunner._html import fetch_url_as_markdown
from initrunner.agent._urls import SSRFBlocked
from initrunner.agent.schema.tools import WebScraperToolConfig
from initrunner.agent.tools._registry import ToolBuildContext, register_tool
from initrunner.ingestion.chunker import chunk_text
from initrunner.ingestion.embeddings import embed_single as _embed_single
from initrunner.stores.base import StoreConfig
from initrunner.stores.factory import create_document_store


def _make_store_config_from_ctx(ctx: ToolBuildContext) -> StoreConfig:
    """Build a StoreConfig from the role in context."""
    from initrunner.stores.base import resolve_store_path

    role = ctx.role
    ingest = role.spec.ingest
    provider = role.spec.model.provider
    name = role.metadata.name
    if ingest is not None:
        return StoreConfig(
            db_path=resolve_store_path(ingest.store_path, name),
            embed_provider=ingest.embeddings.provider or provider,
            embed_model=ingest.embeddings.model,
            store_backend=ingest.store_backend,
            chunking_strategy=ingest.chunking.strategy,
            chunk_size=ingest.chunking.chunk_size,
            chunk_overlap=ingest.chunking.chunk_overlap,
            embed_base_url=ingest.embeddings.base_url,
            embed_api_key_env=ingest.embeddings.api_key_env,
        )
    return StoreConfig(
        db_path=resolve_store_path(None, name),
        embed_provider=provider,
        embed_model="",
    )


@register_tool("web_scraper", WebScraperToolConfig)
def build_web_scraper_toolset(
    config: WebScraperToolConfig,
    ctx: ToolBuildContext,
) -> FunctionToolset:
    """Build a FunctionToolset that scrapes a page and stores it in the document store."""
    store_config = _make_store_config_from_ctx(ctx)
    sandbox = ctx.role.spec.security.tools

    if sandbox is not None:
        from initrunner.agent.tools.retrieval import _validate_store_path

        _validate_store_path(store_config.db_path, sandbox.restrict_db_paths)

    toolset = FunctionToolset()

    @toolset.tool
    def scrape_page(url: str) -> str:
        """Fetch a web page, extract its content, and store it in the document store.

        The content becomes immediately searchable via search_documents.

        Args:
            url: The URL to scrape and store.
        """
        try:
            parsed = urlparse(url)
            hostname = parsed.hostname or ""
        except Exception:
            return "Error: invalid URL"

        if config.allowed_domains:
            if hostname not in config.allowed_domains:
                return f"Error: domain '{hostname}' is not in the allowed domains list"
        elif config.blocked_domains:
            if hostname in config.blocked_domains:
                return f"Error: domain '{hostname}' is blocked"

        try:
            markdown = fetch_url_as_markdown(
                url,
                timeout=config.timeout_seconds,
                user_agent=config.user_agent,
                max_bytes=config.max_content_bytes,
            )
        except SSRFBlocked as e:
            return str(e)
        except Exception as e:
            return f"Error fetching URL: {e}"

        if not markdown.strip():
            return f"No content extracted from {url}"

        # Chunk the content
        chunks = chunk_text(
            markdown,
            source=url,
            strategy=store_config.chunking_strategy,
            chunk_size=store_config.chunk_size,
            chunk_overlap=store_config.chunk_overlap,
        )
        if not chunks:
            return f"No chunks extracted from {url}"

        # Embed
        chunk_texts = [c.text for c in chunks]
        embeddings: list[list[float]] = []
        for ct in chunk_texts:
            embeddings.append(
                _embed_single(
                    store_config.embed_provider,
                    store_config.embed_model,
                    ct,
                    base_url=store_config.embed_base_url,
                    api_key_env=store_config.embed_api_key_env,
                    input_type="document",
                )
            )

        # Store
        dimensions = len(embeddings[0])
        with create_document_store(
            store_config.store_backend, store_config.db_path, dimensions=dimensions
        ) as store:
            store.replace_source(
                source=url,
                texts=chunk_texts,
                embeddings=embeddings,
                ingested_at=datetime.now(UTC).isoformat(),
                content_hash="",
                last_modified=time.time(),
            )

        return f"Stored {len(chunks)} chunks from {url} ({len(markdown):,} chars)"

    return toolset
