"""Turn a roster into runnable agents.

One member or all of them go through the same preparation, so an agent behaves
identically whether it was picked with ``--agent`` or served alongside its
peers.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from initrunner._log import get_logger

if TYPE_CHECKING:
    from collections.abc import Callable

    from pydantic_ai import Agent

    from initrunner.agent.schema.role import RoleDefinition
    from initrunner.group.schema import GroupDefinition, Roster

logger = get_logger("group.prepare")


@dataclass
class PreparedMember:
    """A group member with its agent built."""

    key: str
    path: Path
    role_dir: Path
    role: RoleDefinition
    agent: Agent


class GroupPrepareError(Exception):
    """Raised when a group member cannot be prepared."""


def make_group_overlay(group: GroupDefinition) -> Callable[[RoleDefinition], RoleDefinition]:
    """Return the group settings to apply to a member before its agent is built.

    Only shared stores and group-level observability: everything else about how
    a member behaves comes from its own role file. When the group configures
    neither, this is the identity function and a member runs exactly as it does
    standalone.
    """
    from initrunner.stores.shared import (
        apply_shared_documents,
        apply_shared_memory,
        resolve_shared_store_paths,
    )

    memory_path, document_path = resolve_shared_store_paths(
        group.name, group.shared_memory, group.shared_documents
    )

    def overlay(role: RoleDefinition) -> RoleDefinition:
        if memory_path:
            apply_shared_memory(role, memory_path, group.shared_memory.max_memories)
        if document_path:
            apply_shared_documents(role, group.shared_documents, document_path)
        if group.observability is not None and role.spec.observability is None:
            role.spec.observability = group.observability
        return role

    return overlay


def ingest_shared_documents(group: GroupDefinition) -> None:
    """Ingest the group's shared sources once, before any member queries them."""
    if not (group.shared_documents.enabled and group.shared_documents.sources):
        return

    from initrunner.agent.schema.ingestion import IngestConfig
    from initrunner.agent.schema.security import ResourceLimits
    from initrunner.ingestion.pipeline import run_ingest
    from initrunner.stores.shared import resolve_shared_store_paths

    _memory_path, document_path = resolve_shared_store_paths(
        group.name, group.shared_memory, group.shared_documents
    )
    if not document_path:
        return

    limits = ResourceLimits()
    run_ingest(
        IngestConfig(
            sources=group.shared_documents.sources,
            store_path=document_path,
            store_backend=group.shared_documents.store_backend,
            embeddings=group.shared_documents.embeddings,
            chunking=group.shared_documents.chunking,
        ),
        agent_name=group.name,
        provider="",
        base_dir=group.source_dir,
        max_file_size_mb=limits.max_file_size_mb,
        max_total_ingest_mb=limits.max_total_ingest_mb,
    )


def prepare_group(
    roster: Roster,
    *,
    keys: list[str] | None = None,
    extra_skill_dirs: list[Path] | None = None,
    model_override: str | None = None,
) -> dict[str, PreparedMember]:
    """Build an agent for every requested member.

    Preparation is atomic: if any member fails to build, none are returned, so a
    service never starts up quietly missing an agent.
    """
    from initrunner.agent.loader import load_and_build

    selected = keys if keys is not None else list(roster.members)
    overlay = make_group_overlay(roster.group)
    ingest_shared_documents(roster.group)

    prepared: dict[str, PreparedMember] = {}
    for key in selected:
        member = roster.members.get(key)
        if member is None:
            raise GroupPrepareError(unknown_member_message(roster, key))
        try:
            role, agent = load_and_build(
                member.path,
                extra_skill_dirs=extra_skill_dirs,
                model_override=model_override,
                role_mutator=overlay,
            )
        except Exception as e:
            raise GroupPrepareError(
                f"group '{roster.name}' member '{key}' ({member.path}) failed to build: {e}"
            ) from e
        prepared[key] = PreparedMember(
            key=key,
            path=member.path,
            role_dir=member.role_dir,
            role=role,
            agent=agent,
        )

    return prepared


def unknown_member_message(roster: Roster, key: str) -> str:
    """Error text naming the members that do exist."""
    known = ", ".join(roster.keys())
    return f"group '{roster.name}' has no agent '{key}'. Available agents: {known}"
