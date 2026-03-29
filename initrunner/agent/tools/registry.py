"""Tool builder registry, audit hooks, and build_toolsets orchestrator."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from initrunner.agent.permissions import PolicyToolset
from initrunner.agent.schema.tools import ToolConfig
from initrunner.agent.tools._registry import ToolBuildContext, get_builder, is_run_scoped
from initrunner.stores.base import make_store_config

if TYPE_CHECKING:
    from pydantic_ai.toolsets import AbstractToolset

    from initrunner.agent.schema.role import RoleDefinition


def install_audit_hooks(role: RoleDefinition) -> None:
    """Install audit hooks if enabled in the role's security config."""
    if role.spec.security.tools.audit_hooks_enabled:
        from initrunner.agent.sandbox import install_audit_hook

        install_audit_hook()


def resolve_func_names(tool_configs: list[dict]) -> list[str]:
    """Resolve tool config dicts to registered function names.

    Builds each tool using its registered builder with a minimal context
    and inspects the resulting toolset to extract function names.
    Used to compute always_available for ToolSearchConfig.
    """
    from initrunner.agent.schema.base import ApiVersion, Kind, ModelConfig, RoleMetadata
    from initrunner.agent.schema.role import AgentSpec, RoleDefinition

    dummy_role = RoleDefinition(
        apiVersion=ApiVersion.V1,
        kind=Kind.AGENT,
        metadata=RoleMetadata(name="introspect", description=""),
        spec=AgentSpec(
            role="",
            model=ModelConfig(provider="openai", name="dummy"),
        ),
    )
    dummy_ctx = ToolBuildContext(role=dummy_role)

    func_names: list[str] = []
    for cfg in tool_configs:
        type_name = cfg.get("type")
        if not type_name:
            continue
        builder = get_builder(type_name)
        if builder is None:
            continue
        # Parse the config dict into the registered config class
        from initrunner.agent.tools._registry import get_tool_types

        config_classes = get_tool_types()
        config_cls = config_classes.get(type_name)
        if config_cls is None:
            continue
        try:
            config_obj = config_cls.model_validate(cfg)
            toolset = builder(config_obj, dummy_ctx)
            if hasattr(toolset, "tools"):
                func_names.extend(toolset.tools.keys())  # type: ignore[union-attr]
        except Exception:
            # Builder may fail with dummy context — skip gracefully
            pass
    return func_names


def _instance_key(tool_config: ToolConfig) -> str:
    """Extract multi-instance identifier when available."""
    # ApiToolConfig has a required `name` field
    if hasattr(tool_config, "name") and isinstance(tool_config.name, str):  # type: ignore[union-attr]
        return tool_config.name  # type: ignore[union-attr]
    return ""


def build_toolsets(
    tools: list[ToolConfig],
    role: RoleDefinition,
    role_dir: Path | None = None,
    *,
    prefer_async: bool = False,
) -> list[AbstractToolset]:
    """Build a list of PydanticAI toolsets from tool configs + optional retrieval."""
    from initrunner.agent.tool_events import wrap_observable

    toolsets: list[AbstractToolset] = []
    ctx = ToolBuildContext(role=role, role_dir=role_dir, prefer_async=prefer_async)
    agent_name = role.metadata.name

    install_audit_hooks(role)

    if role.spec.security.docker.enabled:
        from initrunner.agent.docker_sandbox import require_docker

        require_docker()

    for tool in tools:
        if is_run_scoped(tool.type):
            continue  # Built per-run by the runner with fresh state
        builder = get_builder(tool.type)
        if builder:
            toolset = builder(tool, ctx)
            # Inner layer: policy identity-based check
            toolset = PolicyToolset(
                toolset,
                tool.type,
                agent_name,
                instance_key=_instance_key(tool),
            )
            # Middle layer: fnmatch argument-level check (cheap, short-circuits)
            if tool.permissions is not None:
                from initrunner.agent.permissions import PermissionToolset

                toolset = PermissionToolset(toolset, tool.permissions, tool.type)
            # Outer layer: observable status events
            toolsets.append(wrap_observable(toolset))

    # Auto-tools (retrieval, memory) — not user-configured, wired from role spec
    if role.spec.ingest is not None:
        from initrunner.agent.tools.retrieval import build_retrieval_toolset

        ts = build_retrieval_toolset(make_store_config(role), sandbox=role.spec.security.tools)
        ts = PolicyToolset(ts, "retrieval", agent_name)
        toolsets.append(wrap_observable(ts))

    if role.spec.memory is not None:
        from initrunner.agent.tools.memory import build_memory_toolset

        ts = build_memory_toolset(
            role.spec.memory,
            role.metadata.name,
            role.spec.model.provider,  # type: ignore[union-attr]
            sandbox=role.spec.security.tools,
        )
        ts = PolicyToolset(ts, "memory_store", agent_name)
        toolsets.append(wrap_observable(ts))

    return toolsets
