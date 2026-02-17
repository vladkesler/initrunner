"""Shared sync service functions for role discovery, validation, and operations.

These are the core operations used by the CLI, API, and TUI.
Each function is sync and can be called directly or wrapped in asyncio.to_thread().
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

_logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from collections.abc import Callable

    from pydantic_ai import Agent
    from pydantic_ai.messages import ModelMessage

    from initrunner.agent.executor import AutonomousResult, RunResult
    from initrunner.agent.prompt import UserPrompt
    from initrunner.agent.schema import RoleDefinition
    from initrunner.audit.logger import AuditLogger, AuditRecord
    from initrunner.ingestion.pipeline import FileStatus, IngestStats
    from initrunner.stores.base import Memory, MemoryStoreBase, MemoryType, SessionSummary
    from initrunner.triggers.base import TriggerEvent
    from initrunner.triggers.dispatcher import TriggerDispatcher


@dataclass
class DiscoveredRole:
    """A role YAML file discovered on disk."""

    path: Path
    role: RoleDefinition | None = None
    error: str | None = None


_SKIP_DIRS = frozenset(
    {
        "node_modules",
        ".venv",
        "venv",
        "__pycache__",
        ".git",
        ".tox",
        ".mypy_cache",
        ".ruff_cache",
        ".pytest_cache",
        "dist",
        "build",
        ".eggs",
        "_dashboard_static",
        ".hg",
        ".svn",
    }
)


def discover_roles_sync(dirs: list[Path]) -> list[DiscoveredRole]:
    """Scan directories for role YAML files (sync).

    Uses ``os.walk`` with directory pruning to skip common non-role
    directories (node_modules, .venv, .git, etc.) for fast scanning
    even from a large project root.
    """
    import yaml

    from initrunner.agent.loader import RoleLoadError, load_role

    results: list[DiscoveredRole] = []
    seen: set[Path] = set()

    for d in dirs:
        if not d.is_dir():
            continue
        for root, dirnames, filenames in os.walk(d):
            dirnames[:] = sorted(dn for dn in dirnames if dn not in _SKIP_DIRS)
            for fn in sorted(filenames):
                if not (fn.endswith(".yaml") or fn.endswith(".yml")):
                    continue
                p = Path(root) / fn
                resolved = p.resolve()
                if resolved in seen:
                    continue
                seen.add(resolved)

                # Quick check: is it an initrunner role file?
                try:
                    with open(p) as f:
                        raw = yaml.safe_load(f)
                    if not isinstance(raw, dict) or raw.get("apiVersion") != "initrunner/v1":
                        continue
                    if raw.get("kind") != "Agent":
                        continue
                except Exception as e:
                    _logger.debug("Skipping %s: %s", p, e)
                    continue

                try:
                    role = load_role(p)
                    results.append(DiscoveredRole(path=p, role=role))
                except RoleLoadError as e:
                    results.append(DiscoveredRole(path=p, error=str(e)))

    return results


def get_default_role_dirs(explicit_dir: Path | None = None) -> list[Path]:
    """Return directories to scan for role YAML files."""
    from initrunner.config import get_roles_dir

    dirs: list[Path] = []
    if explicit_dir is not None:
        dirs.append(explicit_dir)
    dirs.append(Path.cwd())
    examples = Path.cwd() / "examples" / "roles"
    if examples.is_dir():
        dirs.append(examples)
    global_roles = get_roles_dir()
    if global_roles.is_dir():
        dirs.append(global_roles)
    return dirs


def validate_role_sync(path: Path) -> DiscoveredRole:
    """Validate a single role file (sync)."""
    from initrunner.agent.loader import RoleLoadError, load_role

    try:
        role = load_role(path)
        return DiscoveredRole(path=path, role=role)
    except RoleLoadError as e:
        return DiscoveredRole(path=path, error=str(e))


def build_agent_sync(path: Path) -> tuple[RoleDefinition, Agent]:
    """Load and build an agent from a role file (sync)."""
    from initrunner.agent.loader import load_and_build

    return load_and_build(path)


def execute_run_sync(
    agent: Agent,
    role: RoleDefinition,
    prompt: str | UserPrompt,
    *,
    audit_logger: AuditLogger | None = None,
    message_history: list[ModelMessage] | None = None,
) -> tuple[RunResult, list[ModelMessage]]:
    """Execute a single agent run (sync)."""
    from initrunner.agent.executor import execute_run

    return execute_run(
        agent,
        role,
        prompt,
        audit_logger=audit_logger,
        message_history=message_history,
    )


def execute_autonomous_sync(
    agent: Agent,
    role: RoleDefinition,
    prompt: str | UserPrompt,
    *,
    audit_logger: AuditLogger | None = None,
    memory_store: MemoryStoreBase | None = None,
    max_iterations_override: int | None = None,
) -> AutonomousResult:
    """Execute an autonomous agentic loop (sync)."""
    from initrunner.runner import run_autonomous

    return run_autonomous(
        agent,
        role,
        prompt,
        audit_logger=audit_logger,
        memory_store=memory_store,
        max_iterations_override=max_iterations_override,
    )


def execute_run_stream_sync(
    agent: Agent,
    role: RoleDefinition,
    prompt: str | UserPrompt,
    *,
    audit_logger: AuditLogger | None = None,
    message_history: list[ModelMessage] | None = None,
    on_token: Callable[[str], None] | None = None,
) -> tuple[RunResult, list[ModelMessage]]:
    """Execute a streaming agent run (sync). Call from a worker thread."""
    from initrunner.agent.executor import execute_run_stream

    return execute_run_stream(
        agent,
        role,
        prompt,
        audit_logger=audit_logger,
        message_history=message_history,
        on_token=on_token,
    )


def query_audit_sync(
    *,
    agent_name: str | None = None,
    since: str | None = None,
    until: str | None = None,
    limit: int = 100,
    audit_logger: AuditLogger | None = None,
) -> list[AuditRecord]:
    """Query audit records (sync)."""
    if audit_logger is not None:
        return audit_logger.query(agent_name=agent_name, since=since, until=until, limit=limit)
    from initrunner.audit.logger import DEFAULT_DB_PATH
    from initrunner.audit.logger import AuditLogger as _AuditLogger

    db_path = DEFAULT_DB_PATH
    if not db_path.exists():
        return []
    with _AuditLogger(db_path) as logger:
        return logger.query(agent_name=agent_name, since=since, until=until, limit=limit)


def run_ingest_sync(
    role: RoleDefinition,
    role_path: Path,
    *,
    force: bool = False,
    progress_callback: Callable[[Path, FileStatus], None] | None = None,
) -> IngestStats | None:
    """Run ingestion pipeline (sync)."""
    from initrunner.agent.loader import _load_dotenv
    from initrunner.ingestion.pipeline import run_ingest

    _load_dotenv(role_path.parent)

    if role.spec.ingest is None:
        return None
    return run_ingest(
        role.spec.ingest,
        role.metadata.name,
        provider=role.spec.model.provider,
        base_dir=role_path.parent,
        force=force,
        progress_callback=progress_callback,
    )


def list_memories_sync(
    role: RoleDefinition,
    *,
    category: str | None = None,
    limit: int = 100,
    memory_type: MemoryType | None = None,
) -> list[Memory]:
    """List memories for a role (sync)."""
    from initrunner.stores.factory import open_memory_store

    with open_memory_store(role.spec.memory, role.metadata.name) as store:
        if store is None:
            return []
        return store.list_memories(category=category, limit=limit, memory_type=memory_type)


def clear_memories_sync(
    role: RoleDefinition, *, sessions_only: bool = False, memories_only: bool = False
) -> None:
    """Clear memory store (sync). Delegates to shared domain function."""
    from initrunner.agent.memory_ops import clear_memories

    clear_memories(role, sessions_only=sessions_only, memories_only=memories_only)


def export_memories_sync(role: RoleDefinition) -> list[dict]:
    """Export memories as dicts (sync). Delegates to shared domain function."""
    from initrunner.agent.memory_ops import export_memories

    return export_memories(role)


def save_session_sync(
    role: RoleDefinition,
    session_id: str,
    messages: list[ModelMessage],
) -> bool:
    """Save a chat session to the memory store (sync). Returns True on success."""
    from initrunner.agent.memory_ops import save_session

    return save_session(role, session_id, messages)


def load_session_sync(
    role: RoleDefinition,
    *,
    max_messages: int | None = None,
) -> list[ModelMessage] | None:
    """Load the latest session from the memory store (sync)."""
    from initrunner.agent.memory_ops import load_session

    return load_session(role, max_messages=max_messages)


def list_sessions_sync(role: RoleDefinition, limit: int = 20) -> list[SessionSummary]:
    """List stored sessions for a role (sync)."""
    from initrunner.agent.memory_ops import list_sessions

    return list_sessions(role, limit=limit)


def load_session_by_id_sync(
    role: RoleDefinition,
    session_id: str,
    max_messages: int | None = None,
) -> list[ModelMessage] | None:
    """Load a specific session by ID (sync)."""
    from initrunner.agent.memory_ops import load_session_by_id

    return load_session_by_id(role, session_id, max_messages=max_messages)


def delete_session_sync(role: RoleDefinition, session_id: str) -> bool:
    """Delete a specific session (sync). Returns True if rows were deleted."""
    from initrunner.agent.memory_ops import delete_session

    return delete_session(role, session_id)


def export_session_markdown_sync(role: RoleDefinition, messages: list[ModelMessage]) -> str:
    """Convert a ModelMessage list to a markdown string for export."""
    from pydantic_ai.messages import (
        ModelRequest,
        ModelResponse,
        TextPart,
        UserPromptPart,
    )

    from initrunner.agent.prompt import render_content_as_text

    lines: list[str] = []
    lines.append(f"# Chat Export — {role.metadata.name}")
    lines.append("")

    for msg in messages:
        if isinstance(msg, ModelRequest):
            for part in msg.parts:
                if isinstance(part, UserPromptPart):
                    if isinstance(part.content, str):
                        lines.append(f"**You:** {part.content}")
                    elif isinstance(part.content, list):
                        text_parts = [render_content_as_text(item) for item in part.content]
                        lines.append(f"**You:** {' '.join(text_parts)}")
                    else:
                        lines.append(f"**You:** {part.content}")
                    lines.append("")
        elif isinstance(msg, ModelResponse):
            for part in msg.parts:
                if isinstance(part, TextPart):
                    lines.append(f"**Agent:** {part.content}")
                    lines.append("")

    return "\n".join(lines)


def start_triggers_sync(
    role: RoleDefinition,
    callback: Callable[[TriggerEvent], None],
) -> TriggerDispatcher:
    """Build and start a TriggerDispatcher (sync). Returns the dispatcher."""
    from initrunner.triggers.dispatcher import TriggerDispatcher

    dispatcher = TriggerDispatcher(role.spec.triggers, callback)
    dispatcher.start_all()
    return dispatcher


# ---------------------------------------------------------------------------
# MCP introspection
# ---------------------------------------------------------------------------


def list_mcp_tools_sync(
    role_path: Path,
    index: int | None = None,
) -> list[tuple[str, str, str]]:
    """List tools from MCP servers configured in a role file (sync).

    Returns ``(server_summary, tool_name, tool_description)`` tuples.
    Does not require valid LLM API keys.
    """
    from initrunner.mcp.introspect import list_mcp_tools

    return list_mcp_tools(role_path, index=index)


# ---------------------------------------------------------------------------
# Role creation helpers
# ---------------------------------------------------------------------------


def generate_role_sync(
    description: str,
    *,
    provider: str | None = None,
    model_name: str | None = None,
    name_hint: str | None = None,
) -> str:
    """Generate role YAML from natural language description using LLM."""
    from initrunner.agent.loader import _load_dotenv
    from initrunner.role_generator import generate_role

    _load_dotenv(Path.cwd())

    if provider is None:
        provider = _detect_provider()

    return generate_role(
        description,
        provider=provider,
        model_name=model_name,
        name_hint=name_hint,
    )


def save_role_yaml_sync(path: Path, yaml_content: str) -> RoleDefinition:
    """Validate and save role YAML to disk. Returns parsed role.

    Creates a .bak backup if overwriting an existing file.
    Raises ValueError on invalid YAML or RoleLoadError on schema errors.
    """
    import yaml

    from initrunner.agent.schema import RoleDefinition as RoleDef

    # Parse and validate first
    try:
        raw = yaml.safe_load(yaml_content)
    except yaml.YAMLError as e:
        raise ValueError(f"Invalid YAML syntax: {e}") from e

    if not isinstance(raw, dict):
        raise ValueError("YAML must be a mapping")

    role = RoleDef.model_validate(raw)

    # Backup existing file before overwrite
    if path.exists():
        bak_path = path.with_suffix(path.suffix + ".bak")
        bak_path.write_text(path.read_text())

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml_content)
    return role


def build_role_yaml_sync(
    *,
    name: str,
    description: str = "",
    provider: str = "openai",
    model_name: str | None = None,
    system_prompt: str = "You are a helpful assistant.",
    tools: list[dict] | None = None,
    memory: bool = False,
    ingest: dict | None = None,
    triggers: list[dict] | None = None,
    sinks: list[dict] | None = None,
) -> str:
    """Build role YAML from structured parameters."""
    from initrunner.templates import build_role_yaml

    return build_role_yaml(
        name=name,
        description=description,
        provider=provider,
        model_name=model_name,
        system_prompt=system_prompt,
        tools=tools,
        memory=memory,
        ingest=ingest,
        triggers=triggers,
        sinks=sinks,
    )


def role_to_summary(path: Path, role: RoleDefinition | None = None, error: str | None = None):
    """Build a RoleSummary API model from a role path and optional loaded role."""
    from initrunner.api.models import RoleSummary
    from initrunner.api.state import role_path_to_id

    features: list[str] = []
    if role is not None:
        if role.spec.tools:
            features.append("tools")
        if role.spec.triggers:
            features.append("triggers")
        if role.spec.ingest:
            features.append("ingest")
        if role.spec.memory:
            features.append("memory")
        if role.spec.sinks:
            features.append("sinks")
        if role.spec.skills:
            features.append("skills")

    return RoleSummary(
        id=role_path_to_id(path),
        path=str(path),
        name=role.metadata.name if role else path.stem,
        description=role.metadata.description if role else "",
        model=role.spec.model.to_model_string() if role else "",
        features=features,
        valid=role is not None,
        error=error,
    )


def role_to_detail(path: Path, role: RoleDefinition):
    """Build a RoleDetail API model from a role path and loaded role."""
    from initrunner.api.models import (
        GuardrailsDetail,
        IngestDetail,
        MemoryDetail,
        ModelDetail,
        RoleDetail,
        SinkSummary,
        ToolSummary,
        TriggerSummary,
    )

    summary = role_to_summary(path, role)
    yaml_content = path.read_text()

    ingest = None
    if role.spec.ingest:
        ingest = IngestDetail(
            sources=role.spec.ingest.sources,
            chunking_strategy=role.spec.ingest.chunking.strategy,
            chunk_size=role.spec.ingest.chunking.chunk_size,
            chunk_overlap=role.spec.ingest.chunking.chunk_overlap,
            store_backend=role.spec.ingest.store_backend.value,
        )

    memory = None
    if role.spec.memory:
        memory = MemoryDetail(
            store_backend=role.spec.memory.store_backend.value,
            max_sessions=role.spec.memory.max_sessions,
            max_memories=role.spec.memory.max_memories,
            max_resume_messages=role.spec.memory.max_resume_messages,
            episodic_enabled=role.spec.memory.episodic.enabled,
            episodic_max=role.spec.memory.episodic.max_episodes,
            semantic_enabled=role.spec.memory.semantic.enabled,
            semantic_max=role.spec.memory.semantic.max_memories,
            procedural_enabled=role.spec.memory.procedural.enabled,
            procedural_max=role.spec.memory.procedural.max_procedures,
            consolidation_enabled=role.spec.memory.consolidation.enabled,
        )

    return RoleDetail(
        **summary.model_dump(),
        system_prompt=role.spec.role,
        model_config_detail=ModelDetail(
            provider=role.spec.model.provider,
            name=role.spec.model.name,
            base_url=role.spec.model.base_url,
            temperature=role.spec.model.temperature,
            max_tokens=role.spec.model.max_tokens,
        ),
        guardrails=GuardrailsDetail(
            max_tokens_per_run=role.spec.guardrails.max_tokens_per_run,
            timeout_seconds=role.spec.guardrails.timeout_seconds,
            max_tool_calls=role.spec.guardrails.max_tool_calls,
            max_request_limit=role.spec.guardrails.max_request_limit,
            input_tokens_limit=role.spec.guardrails.input_tokens_limit,
            total_tokens_limit=role.spec.guardrails.total_tokens_limit,
            session_token_budget=role.spec.guardrails.session_token_budget,
            daemon_token_budget=role.spec.guardrails.daemon_token_budget,
            daemon_daily_token_budget=role.spec.guardrails.daemon_daily_token_budget,
        ),
        tools=[ToolSummary(type=t.type, summary=t.summary()) for t in role.spec.tools],
        triggers=[TriggerSummary(type=t.type, summary=t.summary()) for t in role.spec.triggers],
        sinks=[SinkSummary(type=s.type, summary=s.summary()) for s in role.spec.sinks],
        ingest=ingest,
        memory=memory,
        yaml_content=yaml_content,
    )


def _detect_provider() -> str:
    """Auto-detect which provider has an API key available."""
    from initrunner.agent.loader import _PROVIDER_API_KEY_ENVS

    for prov, env_var in _PROVIDER_API_KEY_ENVS.items():
        if os.environ.get(env_var):
            return prov
    return "openai"
