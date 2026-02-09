"""Tool builder registry, audit hooks, and build_toolsets orchestrator."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from initrunner.agent.schema import ToolConfig
from initrunner.agent.tools._registry import ToolBuildContext, get_builder
from initrunner.stores.base import StoreConfig

if TYPE_CHECKING:
    from pydantic_ai.toolsets import AbstractToolset

    from initrunner.agent.schema import RoleDefinition


def _make_store_config(role: RoleDefinition) -> StoreConfig:
    """Build a StoreConfig from a role definition."""
    from initrunner.stores.base import resolve_store_path

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


def install_audit_hooks(role: RoleDefinition) -> None:
    """Install audit hooks if enabled in the role's security config."""
    if role.spec.security.tools.audit_hooks_enabled:
        from initrunner.agent.sandbox import install_audit_hook

        install_audit_hook()


def build_toolsets(
    tools: list[ToolConfig],
    role: RoleDefinition,
    role_dir: Path | None = None,
) -> list[AbstractToolset]:
    """Build a list of PydanticAI toolsets from tool configs + optional retrieval."""
    toolsets: list[AbstractToolset] = []
    ctx = ToolBuildContext(role=role, role_dir=role_dir)

    install_audit_hooks(role)

    for tool in tools:
        builder = get_builder(tool.type)
        if builder:
            toolsets.append(builder(tool, ctx))

    # Auto-tools (retrieval, memory) — not user-configured, wired from role spec
    if role.spec.ingest is not None:
        from initrunner.agent.tools.retrieval import build_retrieval_toolset

        toolsets.append(
            build_retrieval_toolset(_make_store_config(role), sandbox=role.spec.security.tools)
        )

    if role.spec.memory is not None:
        from initrunner.agent.tools.memory import build_memory_toolset

        toolsets.append(
            build_memory_toolset(
                role.spec.memory,
                role.metadata.name,
                role.spec.model.provider,
                sandbox=role.spec.security.tools,
            )
        )

    return toolsets
