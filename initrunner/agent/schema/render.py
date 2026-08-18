"""Render an AgentDocument as readable flat YAML."""

from __future__ import annotations

from typing import Any

import yaml

from initrunner.agent.schema.v3 import AgentChild, AgentDocument

_TOP_LEVEL_ORDER = (
    "name",
    "description",
    "spec_version",
    "tags",
    "author",
    "team",
    "version",
    "dependencies",
    "bundle",
    "model",
    "prompt",
    "output",
    "tools",
    "skills",
    "capabilities",
    "deps_schema",
    "triggers",
    "sinks",
    "ingest",
    "memory",
    "autonomy",
    "reasoning",
    "guardrails",
    "execution",
    "resources",
    "security",
    "observability",
    "auto_skills",
    "tool_search",
    "daemon",
    "agents",
    "run",
    "debate",
    "ensemble",
    "handoff_max_chars",
    "shared_memory",
    "shared_documents",
    "durability",
)

_CHILD_ORDER = (
    "prompt",
    "use",
    "model",
    "tools",
    "tools_mode",
    "environment",
    "triggers",
    "then",
    "after",
    "guardrails",
)


def render_document(document: AgentDocument) -> str:
    """Serialize *document* to public flat YAML."""
    data = document_to_mapping(document)
    return dump_flat_yaml(data)


def document_to_mapping(document: AgentDocument) -> dict[str, Any]:
    """Minimal mapping that ``AgentDocument`` will accept again."""
    out: dict[str, Any] = {
        "name": document.name,
        "spec_version": 3,
    }
    if document.description:
        out["description"] = document.description
    if document.tags:
        out["tags"] = list(document.tags)
    if document.author:
        out["author"] = document.author
    if document.team:
        out["team"] = document.team
    if document.version:
        out["version"] = document.version
    if document.dependencies:
        out["dependencies"] = list(document.dependencies)
    if document.bundle is not None:
        dumped = document.bundle.model_dump(mode="json", exclude_defaults=True, exclude_none=True)
        if dumped:
            out["bundle"] = dumped

    if document.model is not None:
        out["model"] = _model_value(document.model)
    if document.prompt:
        out["prompt"] = document.prompt
    _put_if_dumped(out, "output", document.output)
    if document.tools:
        out["tools"] = _tools_value(document.tools)
    if document.skills:
        out["skills"] = list(document.skills)
    if document.capabilities:
        out["capabilities"] = _capabilities_value(document.capabilities)
    if document.deps_schema is not None:
        out["deps_schema"] = document.deps_schema
    if document.triggers:
        out["triggers"] = _discriminated_value(document.triggers)
    if document.sinks:
        out["sinks"] = _discriminated_value(document.sinks)
    for optional in ("ingest", "memory", "autonomy", "reasoning", "observability"):
        obj = getattr(document, optional)
        if obj is None:
            continue
        dumped = _dump_section(obj)
        out[optional] = dumped if dumped else {}
    _put_if_dumped(out, "guardrails", document.guardrails)
    for section in ("execution", "resources", "auto_skills", "tool_search", "daemon"):
        _put_if_dumped(out, section, getattr(document, section))
    security = document.security
    if security.preset:
        dumped = security.compact_dump(mode="json", exclude_none=True)
    else:
        dumped = _dump_section(security)
    if dumped:
        out["security"] = dumped

    if document.agents:
        out["agents"] = {name: _child_value(child) for name, child in document.agents.items()}
        if document.run is not None:
            out["run"] = document.run
        _put_if_dumped(out, "debate", document.debate)
        _put_if_dumped(out, "ensemble", document.ensemble)
        if document.handoff_max_chars != 4000:
            out["handoff_max_chars"] = document.handoff_max_chars
        _put_if_dumped(out, "shared_memory", document.shared_memory)
        _put_if_dumped(out, "shared_documents", document.shared_documents)
        if document.durability is not None:
            dumped = _dump_section(document.durability)
            if dumped:
                out["durability"] = dumped

    return _order_keys(out, _TOP_LEVEL_ORDER)


def dump_flat_yaml(data: dict[str, Any]) -> str:
    """Dump a mapping with block scalars for multiline strings."""

    class _BlockDumper(yaml.SafeDumper):
        pass

    def _str_representer(dumper: yaml.SafeDumper, value: str) -> yaml.ScalarNode:
        if "\n" in value:
            return dumper.represent_scalar("tag:yaml.org,2002:str", value, style="|")
        return dumper.represent_scalar("tag:yaml.org,2002:str", value)

    _BlockDumper.add_representer(str, _str_representer)
    return yaml.dump(
        data,
        Dumper=_BlockDumper,
        default_flow_style=False,
        sort_keys=False,
        allow_unicode=True,
    )


def _child_value(child: AgentChild) -> Any:
    if (
        child.prompt
        and not child.use
        and not child.tools
        and child.tools_mode == "extend"
        and not child.environment
        and not child.triggers
        and child.then is None
        and not child.after
        and child.guardrails is None
        and child.model is None
    ):
        return child.prompt

    out: dict[str, Any] = {}
    if child.prompt:
        out["prompt"] = child.prompt
    if child.use:
        out["use"] = child.use
    if child.model is not None:
        out["model"] = _model_value(child.model)
    if child.tools:
        out["tools"] = _tools_value(child.tools)
    if child.tools_mode != "extend":
        out["tools_mode"] = child.tools_mode
    if child.environment:
        out["environment"] = dict(child.environment)
    if child.triggers:
        out["triggers"] = _discriminated_value(child.triggers)
    if child.then is not None:
        dumped = child.then.model_dump(mode="json", exclude_defaults=True, exclude_none=True)
        out["then"] = dumped
    if child.after:
        out["after"] = list(child.after)
    if child.guardrails is not None:
        dumped = _dump_section(child.guardrails)
        if dumped:
            out["guardrails"] = dumped
    return _order_keys(out, _CHILD_ORDER)


def _model_value(model: Any) -> Any:
    dumped = model.model_dump(mode="json", exclude_defaults=True, exclude_none=True)
    keys = set(dumped)
    if keys == {"provider", "name"} and dumped["provider"] and dumped["name"]:
        return f"{dumped['provider']}:{dumped['name']}"
    if keys == {"name"} and dumped["name"]:
        return dumped["name"]
    return dumped


def _tools_value(tools: list[Any]) -> list[Any]:
    out: list[Any] = []
    for item in tools:
        dumped = item.model_dump(mode="json", exclude_defaults=True, exclude_none=True)
        dumped = {"type": item.type, **dumped}
        omit = getattr(item, "omit_generated_secret", None)
        if callable(omit):
            omit(dumped)
        if set(dumped) == {"type"}:
            out.append(item.type)
            continue
        rest = {k: v for k, v in dumped.items() if k != "type"}
        out.append({item.type: rest})
    return out


def _discriminated_value(items: list[Any]) -> list[dict[str, Any]]:
    serialized: list[dict[str, Any]] = []
    for item in items:
        dumped = item.model_dump(mode="json", exclude_defaults=True, exclude_none=True)
        dumped = {"type": item.type, **dumped}
        omit = getattr(item, "omit_generated_secret", None)
        if callable(omit):
            omit(dumped)
        serialized.append(dumped)
    return serialized


def _capabilities_value(caps: list[Any]) -> list[Any]:
    yaml_caps: list[Any] = []
    for cap_spec in caps:
        name = cap_spec.name
        args = cap_spec.arguments
        if args is None:
            yaml_caps.append(name)
        elif isinstance(args, tuple) and len(args) == 1:
            yaml_caps.append({name: args[0]})
        else:
            yaml_caps.append({name: args})
    return yaml_caps


def _dump_section(obj: Any) -> dict[str, Any]:
    return obj.model_dump(mode="json", exclude_defaults=True, exclude_none=True)


def _put_if_dumped(out: dict[str, Any], key: str, obj: Any) -> None:
    dumped = _dump_section(obj)
    if dumped:
        out[key] = dumped


def _order_keys(data: dict[str, Any], order: tuple[str, ...]) -> dict[str, Any]:
    known = [key for key in order if key in data]
    extra = [key for key in data if key not in order]
    return {key: data[key] for key in (*known, *extra)}
