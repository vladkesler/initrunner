"""Auto-retrieval tool for ingested documents."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic_ai.toolsets.function import FunctionToolset

from initrunner.agent._paths import _INITRUNNER_DIR, validate_path_within
from initrunner.stores.base import StoreConfig

if TYPE_CHECKING:
    from initrunner.agent.schema import ToolSandboxConfig


from initrunner.ingestion.embeddings import embed_single as _embed_single


def _validate_store_path(db_path: object, restrict: bool) -> None:
    """Validate store paths are under ~/.initrunner/ when restriction is enabled."""
    from pathlib import Path

    if not restrict:
        return
    err, _ = validate_path_within(Path(str(db_path)), [_INITRUNNER_DIR])
    if err:
        raise ValueError(
            f"Store path '{db_path}' is outside ~/.initrunner/. "
            "Set security.tools.restrict_db_paths=false to override."
        )


def build_retrieval_toolset(
    store_config: StoreConfig, *, sandbox: ToolSandboxConfig | None = None
) -> FunctionToolset:
    """Build the auto-retrieval tool for ingested documents."""
    from initrunner.stores.factory import create_document_store

    if sandbox is not None:
        _validate_store_path(store_config.db_path, sandbox.restrict_db_paths)

    toolset = FunctionToolset()

    @toolset.tool
    def search_documents(query: str, top_k: int = 5, source: str | None = None) -> str:
        """Search ingested documents for relevant content.

        Args:
            query: The search query.
            top_k: Number of results to return.
            source: Optional source filter — exact path or glob pattern (e.g. "*.md").
        """
        if not store_config.db_path.exists():
            return "No documents have been ingested yet. Run 'initrunner ingest' first."

        query_embedding = _embed_single(
            store_config.embed_provider,
            store_config.embed_model,
            query,
            base_url=store_config.embed_base_url,
            api_key_env=store_config.embed_api_key_env,
            input_type="query",
        )

        with create_document_store(store_config.store_backend, store_config.db_path) as store:
            results = store.query(query_embedding, top_k=top_k, source_filter=source)

        if not results:
            return "No relevant documents found."

        parts: list[str] = []
        for r in results:
            parts.append(f"[Source: {r.source} | Score: {1 - r.distance:.3f}]\n{r.text}")
        return "\n\n---\n\n".join(parts)

    return toolset
