"""Normalize envelope or flat YAML into AgentDocument + CompositionIR.

Does not load or run agents. Flow child ``needs`` is kept on the IR only.
Inert Flow fields become warnings and are dropped from the public document.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

from initrunner.agent.schema.document import Classification, DocumentClass, classify_mapping
from initrunner.agent.schema.ir import ChildIR, CompositionIR, Shape, ThenIR
from initrunner.agent.schema.v3 import _NAME_RE, AgentChild, AgentDocument, ThenConfig
from initrunner.flow.schema import DelegateSinkConfig, SharedDocumentsConfig
from initrunner.team.schema import TeamDocumentsConfig

INERT_FLOW_CHILD_FIELDS: dict[str, str] = {
    "restart": "accepted in Flow YAML, never executed",
    "health_check": "accepted in Flow YAML, never executed",
    "environment": "accepted in Flow YAML, never executed",
    "trigger": "daemon uses the referenced role file's triggers, not this field",
}


@dataclass(frozen=True)
class NormalizeResult:
    classification: Classification
    document: AgentDocument
    ir: CompositionIR
    warnings: tuple[str, ...]


class NormalizeError(ValueError):
    """Raised when a document cannot be normalized into an agent."""


def normalize_mapping(data: object) -> NormalizeResult:
    """Classify *data* and produce a v3 document plus IR."""
    classification = classify_mapping(data)
    cls = classification.document_class
    if cls is DocumentClass.INVALID:
        raise NormalizeError(classification.reason)
    if cls is DocumentClass.REMOVED_COMPOSE:
        raise NormalizeError(classification.reason)
    if cls is DocumentClass.SERVICE:
        raise NormalizeError("Service documents are not agents")
    if cls is DocumentClass.TEST_SUITE:
        raise NormalizeError("TestSuite documents are not agents")
    if not isinstance(data, dict):
        raise NormalizeError("expected a mapping")

    mapping = cast(dict[str, Any], data)
    extra_needs: dict[str, tuple[str, ...]] = {}
    warnings: list[str] = []

    if cls is DocumentClass.FLAT_AGENT:
        document = AgentDocument.model_validate(mapping)
    elif cls is DocumentClass.ENVELOPE_AGENT:
        document = AgentDocument.model_validate(_envelope_agent_to_v3(mapping))
    elif cls is DocumentClass.ENVELOPE_TEAM:
        document = AgentDocument.model_validate(_envelope_team_to_v3(mapping))
    elif cls is DocumentClass.ENVELOPE_FLOW:
        raw, extra_needs, warnings = _envelope_flow_to_v3(mapping)
        document = AgentDocument.model_validate(raw)
    else:
        raise NormalizeError(f"unsupported document class: {cls}")

    ir = document_to_ir(document, extra_needs=extra_needs, warnings=tuple(warnings))
    return NormalizeResult(classification, document, ir, tuple(warnings))


def document_to_ir(
    document: AgentDocument,
    *,
    extra_needs: dict[str, tuple[str, ...]] | None = None,
    warnings: tuple[str, ...] = (),
) -> CompositionIR:
    """Compile a validated v3 document into the canonical IR."""
    extra_needs = extra_needs or {}
    model = _dump_model(document.model)
    tools = _dump_tools(document.tools)

    if not document.agents:
        return CompositionIR(
            name=document.name,
            shape="solo",
            prompt=document.prompt,
            model=model,
            tools=tools,
            description=document.description,
            tags=tuple(document.tags),
            author=document.author,
            team=document.team,
            version=document.version,
            dependencies=tuple(document.dependencies),
            spec_version=document.spec_version,
            warnings=warnings,
        )

    has_then = any(child.then is not None for child in document.agents.values())
    has_after = any(child.after for child in document.agents.values())
    is_graph = has_then or has_after
    # Only a group of independent agents survives validation without a run
    # preset, and it hands off to nothing.
    is_roster = not is_graph and document.run is None
    children = tuple(
        _child_ir(name, child, extra_needs.get(name, ())) for name, child in document.agents.items()
    )
    if is_graph:
        shape: Shape = "graph"
    elif is_roster:
        shape = "roster"
    else:
        shape = "preset"
    return CompositionIR(
        name=document.name,
        shape=shape,
        prompt=None,
        model=model,
        tools=tools,
        run=document.run,
        children=children,
        handoff=None if is_roster else ("flow" if is_graph else "team"),
        description=document.description,
        tags=tuple(document.tags),
        author=document.author,
        team=document.team,
        version=document.version,
        dependencies=tuple(document.dependencies),
        spec_version=document.spec_version,
        handoff_max_chars=document.handoff_max_chars,
        warnings=warnings,
        extras={
            "shared_memory": document.shared_memory.model_dump(),
            "shared_documents": document.shared_documents.model_dump(),
            "durability": (
                document.durability.model_dump() if document.durability is not None else None
            ),
        },
    )


def _child_ir(name: str, child: AgentChild, extra_needs: tuple[str, ...]) -> ChildIR:
    then = None
    if child.then is not None:
        then = _then_ir(child.then)
    needs = tuple(child.after) if child.after else extra_needs
    return ChildIR(
        name=name,
        prompt=child.prompt,
        use=child.use,
        model=_dump_model(child.model),
        tools=_dump_tools(child.tools),
        tools_mode=child.tools_mode,
        environment=tuple(sorted(child.environment.items())),
        triggers=tuple(t.model_dump() for t in child.triggers),
        then=then,
        needs=needs,
    )


def _then_ir(then: ThenConfig) -> ThenIR:
    targets = then.to if isinstance(then.to, list) else [then.to]
    return ThenIR(
        to=tuple(targets),
        strategy=then.strategy,
        ensemble=then.ensemble.model_dump() if then.ensemble is not None else None,
        loop_back=then.loop_back.model_dump() if then.loop_back is not None else None,
        keep_existing_sinks=then.keep_existing_sinks,
        queue_size=then.queue_size,
        timeout_seconds=then.timeout_seconds,
        circuit_breaker_threshold=then.circuit_breaker_threshold,
        circuit_breaker_reset_seconds=then.circuit_breaker_reset_seconds,
    )


def _dump_model(model: Any) -> dict[str, Any] | None:
    if model is None:
        return None
    return model.model_dump(exclude_unset=True)


def _dump_tools(tools: list[Any]) -> tuple[dict[str, Any], ...]:
    return tuple(t.model_dump() for t in tools)


def _identity_from_metadata(meta: Any) -> dict[str, Any]:
    out: dict[str, Any] = {
        "name": meta.name,
        "description": meta.description,
        "tags": list(meta.tags),
        "author": meta.author,
        "team": meta.team,
        "version": meta.version,
        "dependencies": list(meta.dependencies),
    }
    if getattr(meta, "bundle", None) is not None:
        out["bundle"] = meta.bundle.model_dump()
    return out


def _envelope_agent_to_v3(data: dict[str, Any]) -> dict[str, Any]:
    from initrunner.deprecations import validate_role_dict

    role, _hits = validate_role_dict(data)
    return role_to_v3_mapping(role)


def role_to_v3_mapping(role: Any) -> dict[str, Any]:
    """Project a ``RoleDefinition`` onto a flat AgentDocument mapping."""
    spec = role.spec
    out = _identity_from_metadata(role.metadata)
    out["prompt"] = spec.role
    if spec.model is not None:
        dumped = spec.model.model_dump(mode="json", exclude_defaults=True, exclude_none=True)
        if dumped:
            out["model"] = dumped
    if spec.tools:
        out["tools"] = _dump_discriminated(spec.tools)
    if spec.skills:
        out["skills"] = list(spec.skills)
    if spec.capabilities:
        out["capabilities"] = list(spec.capabilities)
    if spec.deps_schema is not None:
        out["deps_schema"] = spec.deps_schema
    if spec.triggers:
        out["triggers"] = _dump_discriminated(spec.triggers)
    if spec.sinks:
        out["sinks"] = _dump_discriminated(spec.sinks)
    for optional in ("ingest", "memory", "autonomy", "reasoning", "observability"):
        obj = getattr(spec, optional)
        if obj is None:
            continue
        dumped = obj.model_dump(mode="json", exclude_defaults=True, exclude_none=True)
        out[optional] = dumped if dumped else {}
    guardrails = spec.guardrails.model_dump(mode="json", exclude_defaults=True, exclude_none=True)
    if guardrails:
        out["guardrails"] = guardrails
    output = spec.output.model_dump(mode="json", exclude_defaults=True, exclude_none=True)
    if output:
        out["output"] = output
    for section in ("execution", "resources", "auto_skills", "tool_search", "daemon"):
        obj = getattr(spec, section)
        dumped = obj.model_dump(mode="json", exclude_defaults=True, exclude_none=True)
        if dumped:
            out[section] = dumped
    security = spec.security
    if security.preset:
        dumped = security.compact_dump(mode="json", exclude_none=True)
    else:
        dumped = security.model_dump(mode="json", exclude_defaults=True, exclude_none=True)
    if dumped:
        out["security"] = dumped
    return out


def _dump_discriminated(items: list[Any]) -> list[dict[str, Any]]:
    """Dump union items without dropping the ``type`` discriminator."""
    serialized: list[dict[str, Any]] = []
    for item in items:
        dumped = item.model_dump(mode="json", exclude_defaults=True, exclude_none=True)
        dumped = {"type": item.type, **dumped}
        omit = getattr(item, "omit_generated_secret", None)
        if callable(omit):
            omit(dumped)
        serialized.append(dumped)
    return serialized


def _envelope_team_to_v3(data: dict[str, Any]) -> dict[str, Any]:
    from initrunner.deprecations import SchemaKind, apply_deprecations
    from initrunner.team.schema import TeamDefinition

    migrated, _hits = apply_deprecations(data, SchemaKind.TEAM)
    team = TeamDefinition.model_validate(migrated)
    spec = team.spec
    out = _identity_from_metadata(team.metadata)
    if spec.model is not None:
        out["model"] = spec.model.model_dump()
    out["tools"] = _dump_discriminated(spec.tools) if spec.tools else []
    out["guardrails"] = {
        "max_tokens_per_run": spec.guardrails.max_tokens_per_run,
        "max_tool_calls": spec.guardrails.max_tool_calls,
        "timeout_seconds": spec.guardrails.timeout_seconds,
        "team_token_budget": spec.guardrails.team_token_budget,
        "team_timeout_seconds": spec.guardrails.team_timeout_seconds,
    }
    out["handoff_max_chars"] = spec.handoff_max_chars
    out["run"] = spec.strategy
    out["debate"] = spec.debate.model_dump()
    out["ensemble"] = spec.ensemble.model_dump()
    out["shared_memory"] = spec.shared_memory.model_dump()
    out["shared_documents"] = spec.shared_documents.model_dump()
    if spec.observability is not None:
        out["observability"] = spec.observability.model_dump()
    agents: dict[str, Any] = {}
    for name, persona in spec.personas.items():
        child: dict[str, Any] = {"prompt": persona.role}
        if persona.model is not None:
            child["model"] = persona.model.model_dump()
        if persona.tools:
            child["tools"] = _dump_discriminated(persona.tools)
        if persona.tools_mode != "extend":
            child["tools_mode"] = persona.tools_mode
        if persona.environment:
            child["environment"] = dict(persona.environment)
        agents[name] = child
    out["agents"] = agents
    return out


def _envelope_flow_to_v3(
    data: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, tuple[str, ...]], list[str]]:
    from initrunner.deprecations import validate_flow_dict

    flow, _hits = validate_flow_dict(data)
    raw_agents = data.get("spec", {}).get("agents", {})
    warnings: list[str] = []
    extra_needs: dict[str, tuple[str, ...]] = {}
    name = flow.metadata.name
    if not _NAME_RE.fullmatch(name):
        raise NormalizeError(f"rename metadata.name to kebab-case (got {name!r})")
    out: dict[str, Any] = {
        "name": name,
        "description": flow.metadata.description,
        "shared_memory": flow.spec.shared_memory.model_dump(),
        "shared_documents": _flow_docs_to_team(flow.spec.shared_documents),
    }
    if flow.spec.durability.enabled:
        out["durability"] = flow.spec.durability.model_dump()

    agents: dict[str, Any] = {}
    for name, cfg in flow.spec.agents.items():
        raw_child = raw_agents.get(name, {}) if isinstance(raw_agents, dict) else {}
        if isinstance(raw_child, dict):
            for field_name, message in INERT_FLOW_CHILD_FIELDS.items():
                if field_name in raw_child:
                    warnings.append(f"agents.{name}.{field_name}: {message}")
        child: dict[str, Any] = {"use": cfg.role}
        if cfg.sink is not None:
            child["then"] = _sink_to_then(cfg.sink)
        if cfg.needs:
            child["after"] = list(cfg.needs)
            extra_needs[name] = tuple(cfg.needs)
        agents[name] = child
    out["agents"] = agents
    return out, extra_needs, warnings


def _sink_to_then(sink: DelegateSinkConfig) -> dict[str, Any]:
    dumped: dict[str, Any] = {
        "to": sink.target,
        "strategy": sink.strategy,
        "keep_existing_sinks": sink.keep_existing_sinks,
        "queue_size": sink.queue_size,
        "timeout_seconds": sink.timeout_seconds,
        "circuit_breaker_threshold": sink.circuit_breaker_threshold,
        "circuit_breaker_reset_seconds": sink.circuit_breaker_reset_seconds,
    }
    if sink.ensemble is not None:
        dumped["ensemble"] = sink.ensemble.model_dump()
    if sink.loop_back is not None:
        dumped["loop_back"] = sink.loop_back.model_dump()
    return dumped


def _flow_docs_to_team(docs: SharedDocumentsConfig) -> dict[str, Any]:
    return TeamDocumentsConfig(
        enabled=docs.enabled,
        store_path=docs.store_path,
        store_backend=docs.store_backend,
        embeddings=docs.embeddings,
    ).model_dump()
