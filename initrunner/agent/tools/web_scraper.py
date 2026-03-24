"""Web scraper tool: fetch, chunk, embed, and store web pages."""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime

from pydantic_ai.toolsets.function import FunctionToolset

from initrunner._html import fetch_url_as_markdown
from initrunner.agent._urls import SSRFBlocked, check_domain_filter
from initrunner.agent.schema.tools import WebScraperToolConfig
from initrunner.agent.tools._registry import ToolBuildContext, register_tool
from initrunner.ingestion.chunker import chunk_text
from initrunner.ingestion.embeddings import embed_single as _embed_single
from initrunner.stores.base import make_store_config
from initrunner.stores.factory import create_document_store


def _store_chunks(
    store_config,
    url: str,
    chunk_texts: list[str],
    embeddings: list[list[float]],
) -> str:
    """Shared storage logic for sync and async scrape paths."""
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
    return f"Stored {len(chunk_texts)} chunks from {url}"


@register_tool("web_scraper", WebScraperToolConfig)
def build_web_scraper_toolset(
    config: WebScraperToolConfig,
    ctx: ToolBuildContext,
) -> FunctionToolset:
    """Build a FunctionToolset that scrapes a page and stores it in the document store."""
    store_config = make_store_config(ctx.role)
    sandbox = ctx.role.spec.security.tools

    if sandbox is not None:
        from initrunner.agent.tools.retrieval import _validate_store_path

        _validate_store_path(store_config.db_path, sandbox.restrict_db_paths)

    toolset = FunctionToolset()

    if ctx.prefer_async:

        @toolset.tool_plain
        async def scrape_page(url: str) -> str:
            """Fetch a web page, extract its content, and store it in the document store.

            The content becomes immediately searchable via search_documents.

            Args:
                url: The URL to scrape and store.
            """
            error = check_domain_filter(url, config.allowed_domains, config.blocked_domains)
            if error:
                return error

            try:
                from initrunner._html import fetch_url_as_markdown_async

                markdown = await fetch_url_as_markdown_async(
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

            chunks = chunk_text(
                markdown,
                source=url,
                strategy=store_config.chunking_strategy,
                chunk_size=store_config.chunk_size,
                chunk_overlap=store_config.chunk_overlap,
            )
            if not chunks:
                return f"No chunks extracted from {url}"

            # Embed concurrently using asyncio.gather
            chunk_texts = [c.text for c in chunks]

            from initrunner.ingestion.embeddings import embed_single_async

            embed_tasks = [
                embed_single_async(
                    store_config.embed_provider,
                    store_config.embed_model,
                    ct,
                    base_url=store_config.embed_base_url,
                    api_key_env=store_config.embed_api_key_env,
                    input_type="document",
                )
                for ct in chunk_texts
            ]
            embeddings = await asyncio.gather(*embed_tasks)

            result = _store_chunks(store_config, url, chunk_texts, list(embeddings))
            return f"{result} ({len(markdown):,} chars)"

    else:

        @toolset.tool_plain
        def scrape_page(url: str) -> str:
            """Fetch a web page, extract its content, and store it in the document store.

            The content becomes immediately searchable via search_documents.

            Args:
                url: The URL to scrape and store.
            """
            error = check_domain_filter(url, config.allowed_domains, config.blocked_domains)
            if error:
                return error

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

            chunks = chunk_text(
                markdown,
                source=url,
                strategy=store_config.chunking_strategy,
                chunk_size=store_config.chunk_size,
                chunk_overlap=store_config.chunk_overlap,
            )
            if not chunks:
                return f"No chunks extracted from {url}"

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

            result = _store_chunks(store_config, url, chunk_texts, embeddings)
            return f"{result} ({len(markdown):,} chars)"

    return toolset
