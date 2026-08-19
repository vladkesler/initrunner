"""Adapt a v3 AgentDocument back onto today's Role / Team / Flow types.

Keeps the existing executors. Public YAML is flat; runners still consume
envelope models until those executors merge.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from initrunner.agent.schema.base import ApiVersion, Kind, RoleMetadata
from initrunner.agent.schema.document import DocumentClass, classify_mapping
from initrunner.agent.schema.ir import CompositionIR
from initrunner.agent.schema.normalize import normalize_mapping
from initrunner.agent.schema.role import AgentSpec, RoleDefinition
from initrunner.agent.schema.v3 import AgentChild, AgentDocument, ThenConfig
from initrunner.flow.schema import (
    DelegateSinkConfig,
    DurabilityConfig,
    FlowAgentConfig,
    FlowDefinition,
    FlowMetadata,
    FlowSpec,
)
from initrunner.team.schema import PersonaConfig, TeamDefinition, TeamGuardrails, TeamSpec


class AdaptError(ValueError):
    """Raised when a document cannot be adapted to a runner type."""


def run_kind_from_mapping(data: dict[str, Any]) -> str:
    """Legacy kind the current ``run`` dispatcher understands."""
    classification = classify_mapping(data)
    if classification.document_class is DocumentClass.FLAT_AGENT:
        agents = data.get("agents")
        if not isinstance(agents, dict) or not agents:
            return "Agent"
        if any(
            isinstance(v, dict) and (v.get("then") is not None or v.get("after"))
            for v in agents.values()
        ):
            return "Flow"
        if len(agents) == 1:
            return "Agent"
        return "Team"
    if classification.legacy_kind in {"Agent", "Team", "Flow", "Service", "TestSuite"}:
        return classification.legacy_kind
    if classification.document_class is DocumentClass.REMOVED_COMPOSE:
        return "Compose"
    return "Agent"


def document_to_role(document: AgentDocument, *, base_dir: Path | None = None) -> RoleDefinition:
    """Solo (or single-child preset) → RoleDefinition."""
    if document.agents and len(document.agents) == 1:
        name, child = next(iter(document.agents.items()))
        return _child_to_role(name, child, document, base_dir)
    if document.agents:
        raise AdaptError("composed documents with multiple agents are not a solo role")
    if not document.prompt:
        raise AdaptError("solo document has no prompt")
    return _spec_to_role(
        name=document.name,
        description=document.description,
        tags=document.tags,
        prompt=document.prompt,
        document=document,
        model=document.model,
        tools=list(document.tools),
    )


def document_to_team(document: AgentDocument, *, base_dir: Path | None = None) -> TeamDefinition:
    """Preset composition → TeamDefinition."""
    if not document.agents or len(document.agents) < 2:
        raise AdaptError("team adapter needs at least two agents")
    if any(c.then is not None or c.after for c in document.agents.values()):
        raise AdaptError("graph documents are not teams; use the flow adapter")

    personas: dict[str, PersonaConfig] = {}
    member_roles: dict[str, RoleDefinition] = {}
    member_dirs: dict[str, Path] = {}
    for name, child in document.agents.items():
        personas[name] = _child_to_persona(name, child, document, base_dir)
        if child.use:
            # _child_to_persona already rejected a missing base_dir.
            assert base_dir is not None
            member_roles[name] = _team_member_role(name, child, document, base_dir)
            member_dirs[name] = (base_dir / child.use).resolve().parent

    g = document.guardrails
    spec = TeamSpec(
        model=document.model,
        personas=personas,
        tools=list(document.tools),
        guardrails=TeamGuardrails(
            max_tokens_per_run=g.max_tokens_per_run,
            max_tool_calls=g.max_tool_calls,
            timeout_seconds=g.timeout_seconds,
            team_token_budget=g.team_token_budget,
            team_timeout_seconds=g.team_timeout_seconds,
        ),
        handoff_max_chars=document.handoff_max_chars,
        shared_memory=document.shared_memory,
        shared_documents=document.shared_documents,
        observability=document.observability,
        strategy=document.run or "sequential",
        debate=document.debate,
        ensemble=document.ensemble,
    )
    team = TeamDefinition(
        apiVersion=ApiVersion.V1,
        kind="Team",
        metadata=RoleMetadata(
            name=document.name,
            description=document.description,
            tags=list(document.tags),
            author=document.author,
            team=document.team,
            version=document.version,
            dependencies=list(document.dependencies),
            bundle=document.bundle,
        ),
        spec=spec,
    )
    for name, role in member_roles.items():
        team.set_member_provenance(name, role, member_dirs[name])
    return team


def document_to_flow(document: AgentDocument, *, base_dir: Path | None = None) -> FlowDefinition:
    """Graph composition → FlowDefinition."""
    if not document.agents:
        raise AdaptError("flow adapter needs agents")

    inbound: dict[str, list[str]] = {name: [] for name in document.agents}
    agents: dict[str, FlowAgentConfig] = {}
    for name, child in document.agents.items():
        sink = _then_to_sink(child.then) if child.then is not None else None
        if sink is not None:
            targets = sink.target if isinstance(sink.target, list) else [sink.target]
            for target in targets:
                inbound.setdefault(target, []).append(name)
        if child.use:
            inline_role = (
                _child_to_role(name, child, document, base_dir)
                if _child_has_role_overrides(child)
                else None
            )
            agents[name] = FlowAgentConfig(
                role=child.use,
                inline_role=inline_role,
                sink=sink,
            )
        else:
            agents[name] = FlowAgentConfig(
                role="",
                inline_role=_child_to_role(name, child, document, base_dir),
                sink=sink,
            )

    for name, cfg in agents.items():
        child = document.agents[name]
        if child.after:
            cfg.needs = list(child.after)
        else:
            cfg.needs = list(inbound.get(name, []))

    spec = FlowSpec(
        agents=agents,
        shared_memory=document.shared_memory,
        shared_documents=_team_docs_to_flow(document.shared_documents),
        durability=document.durability or DurabilityConfig(),
    )
    return FlowDefinition(
        apiVersion="initrunner/v1",
        kind="Flow",
        metadata=FlowMetadata(name=document.name, description=document.description),
        spec=spec,
    )


def adapt_mapping(
    data: dict[str, Any],
    *,
    base_dir: Path | None = None,
) -> tuple[str, RoleDefinition | TeamDefinition | FlowDefinition, CompositionIR]:
    """Normalize *data* and return ``(legacy_kind, runner_model, ir)``."""
    result = normalize_mapping(data)
    kind = run_kind_from_mapping(data)
    if kind == "Team":
        return kind, document_to_team(result.document, base_dir=base_dir), result.ir
    if kind == "Flow":
        return kind, document_to_flow(result.document, base_dir=base_dir), result.ir
    if kind == "Agent":
        return kind, document_to_role(result.document, base_dir=base_dir), result.ir
    raise AdaptError(f"cannot adapt document as {kind}")


def _spec_to_role(
    *,
    name: str,
    description: str,
    tags: list[str],
    prompt: str,
    document: AgentDocument,
    model: Any,
    tools: list[Any],
) -> RoleDefinition:
    spec = AgentSpec(
        role=prompt,
        model=model,
        output=document.output,
        tools=tools,
        skills=list(document.skills),
        capabilities=list(document.capabilities),
        deps_schema=document.deps_schema,
        triggers=list(document.triggers),
        sinks=list(document.sinks),
        ingest=document.ingest,
        memory=document.memory,
        autonomy=document.autonomy,
        reasoning=document.reasoning,
        guardrails=document.guardrails,
        execution=document.execution,
        resources=document.resources,
        security=document.security,
        observability=document.observability,
        auto_skills=document.auto_skills,
        tool_search=document.tool_search,
        daemon=document.daemon,
    )
    return RoleDefinition(
        apiVersion=ApiVersion.V1,
        kind=Kind.AGENT,
        metadata=RoleMetadata(
            name=name,
            description=description,
            tags=list(tags),
            author=document.author,
            team=document.team,
            version=document.version,
            dependencies=list(document.dependencies),
            bundle=document.bundle,
            spec_version=2,
        ),
        spec=spec,
    )


def _child_to_role(
    name: str,
    child: AgentChild,
    document: AgentDocument,
    base_dir: Path | None,
) -> RoleDefinition:
    prompt, model, tools = _resolved_child(name, child, document, base_dir)
    if child.use:
        if base_dir is None:
            raise AdaptError(f"agent '{name}' has use: {child.use} but no base directory")
        from initrunner.agent.loader import load_role

        role = load_role((base_dir / child.use).resolve())
    else:
        role = _spec_to_role(
            name=name,
            description=document.description,
            tags=document.tags,
            prompt=prompt,
            document=document,
            model=model,
            tools=tools,
        )

    updates: dict[str, Any] = {
        "role": prompt,
        "model": model,
        "tools": tools,
    }
    if "triggers" in child.model_fields_set:
        updates["triggers"] = list(child.triggers)
    if child.guardrails is not None:
        guardrail_updates = child.guardrails.model_dump(
            exclude_unset=True,
            exclude={"team_token_budget", "team_timeout_seconds"},
        )
        updates["guardrails"] = role.spec.guardrails.model_copy(update=guardrail_updates)
    return role.model_copy(update={"spec": role.spec.model_copy(update=updates)})


def _child_has_role_overrides(child: AgentChild) -> bool:
    """Whether a referenced flow child needs an in-memory merged role."""
    return bool(
        child.model_fields_set
        & {"prompt", "model", "tools", "tools_mode", "triggers", "guardrails"}
    )


def _child_to_persona(
    name: str,
    child: AgentChild,
    document: AgentDocument,
    base_dir: Path | None,
) -> PersonaConfig:
    prompt, _model, _tools = _resolved_child(name, child, document, base_dir)
    persona_tools = list(child.tools)
    persona_model = child.model
    if child.use:
        if base_dir is None:
            raise AdaptError(f"agent '{name}' has use: {child.use} but no base directory")
        from initrunner.agent.loader import load_role

        ref = load_role((base_dir / child.use).resolve())
        persona_tools = list(ref.spec.tools) + list(child.tools)
        persona_model = child.model or ref.spec.model
    return PersonaConfig(
        role=prompt,
        model=persona_model,
        tools=persona_tools,
        tools_mode=child.tools_mode,
        environment=dict(child.environment),
    )


def _team_member_role(
    name: str,
    child: AgentChild,
    document: AgentDocument,
    base_dir: Path,
) -> RoleDefinition:
    """Full referenced role backing a ``use:`` persona.

    ``PersonaConfig`` only carries prompt/model/tools, so the referenced role's
    skills, memory, ingest, output schema, security and the rest would be lost
    if the runner rebuilt the persona from it. Team-level guardrails and
    observability are overlaid only where the document set them explicitly, so
    the referenced role's own settings otherwise stand.
    """
    role = _child_to_role(name, child, document, base_dir)
    if "guardrails" in document.model_fields_set:
        overlay = document.guardrails.model_dump(
            exclude_unset=True,
            exclude={"team_token_budget", "team_timeout_seconds"},
        )
        if overlay:
            role.spec.guardrails = role.spec.guardrails.model_copy(update=overlay)
    if document.observability is not None and role.spec.observability is None:
        role.spec.observability = document.observability
    return role


def _resolved_child(
    name: str,
    child: AgentChild,
    document: AgentDocument,
    base_dir: Path | None,
) -> tuple[str, Any, list[Any]]:
    prompt = child.prompt
    model = child.model or document.model
    if child.tools_mode == "extend":
        tools = list(document.tools) + list(child.tools)
    else:
        tools = list(child.tools)
    if child.use:
        if base_dir is None:
            raise AdaptError(f"agent '{name}' has use: {child.use} but no base directory")
        ref_path = (base_dir / child.use).resolve()
        from initrunner.agent.loader import load_role

        ref = load_role(ref_path)
        if not child.prompt and not ref.spec.role:
            raise AdaptError(f"agent '{name}' referenced {child.use} with no prompt")
        prompt = child.prompt or ref.spec.role
        model = child.model or ref.spec.model or document.model
        if child.tools_mode == "replace" and child.tools:
            tools = list(child.tools)
        elif child.tools_mode == "replace":
            tools = list(ref.spec.tools)
        else:
            tools = list(document.tools) + list(ref.spec.tools) + list(child.tools)
    if not prompt:
        raise AdaptError(f"agent '{name}' has no prompt")
    return prompt, model, tools


def _then_to_sink(then: ThenConfig) -> DelegateSinkConfig:
    return DelegateSinkConfig(
        target=then.to,
        strategy=then.strategy,
        ensemble=then.ensemble,
        loop_back=then.loop_back,
        keep_existing_sinks=then.keep_existing_sinks,
        queue_size=then.queue_size,
        timeout_seconds=then.timeout_seconds,
        circuit_breaker_threshold=then.circuit_breaker_threshold,
        circuit_breaker_reset_seconds=then.circuit_breaker_reset_seconds,
    )


def _team_docs_to_flow(docs: Any) -> Any:
    from initrunner.flow.schema import SharedDocumentsConfig

    return SharedDocumentsConfig(
        enabled=docs.enabled,
        store_path=docs.store_path,
        store_backend=docs.store_backend,
        embeddings=docs.embeddings,
    )
