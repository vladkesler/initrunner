"""Role generation, YAML persistence, and provider detection."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from initrunner.agent.schema.role import RoleDefinition

_ExplainerFn = Callable[["RoleDefinition"], str | None]


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

    from initrunner.deprecations import CURRENT_ROLE_SPEC_VERSION, validate_role_dict

    # Parse and validate first
    try:
        raw = yaml.safe_load(yaml_content)
    except yaml.YAMLError as e:
        raise ValueError(f"Invalid YAML syntax: {e}") from e

    if not isinstance(raw, dict):
        raise ValueError("YAML must be a mapping")

    # Normalize spec_version to current before validation and write
    raw.setdefault("metadata", {})["spec_version"] = CURRENT_ROLE_SPEC_VERSION
    role, _hits = validate_role_dict(raw)

    # Backup existing file before overwrite
    if path.exists():
        bak_path = path.with_suffix(path.suffix + ".bak")
        bak_path.write_text(path.read_text())

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(canonicalize_role_yaml(role))
    return role


def build_role_yaml_sync(
    *,
    name: str,
    description: str = "",
    provider: str = "openai",
    model_name: str | None = None,
    system_prompt: str = "You are a helpful assistant.",
    tools: list[dict] | None = None,
    tags: list[str] | None = None,
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
        tags=tags,
        memory=memory,
        ingest=ingest,
        triggers=triggers,
        sinks=sinks,
    )


def canonicalize_role_yaml(role: RoleDefinition) -> str:
    """Serialize a RoleDefinition to minimal YAML, omitting default and null values.

    Uses Pydantic's ``exclude_defaults`` + ``exclude_none`` to strip fields that
    match their schema default.  ``metadata.spec_version`` is always re-injected.
    Multiline strings render as YAML block scalars for readability.
    """
    import yaml

    data = role.model_dump(mode="json", by_alias=True, exclude_defaults=True, exclude_none=True)

    # Discriminated union items (tools, triggers, sinks) need special handling:
    # exclude_defaults strips the `type` discriminator, but we need it for
    # deserialization. Dump each item with exclude_defaults, then re-inject type.
    for key in ("tools", "triggers", "sinks"):
        items = getattr(role.spec, key, [])
        if items:
            serialized = []
            for item in items:
                d = item.model_dump(mode="json", exclude_defaults=True, exclude_none=True)
                d = {"type": item.type, **d}
                serialized.append(d)
            data.setdefault("spec", {})[key] = serialized

    # Remove empty dicts/lists left after stripping defaults
    def _prune(d: dict) -> dict:
        return {
            k: _prune(v) if isinstance(v, dict) else v
            for k, v in d.items()
            if v != {} and v != [] and v is not None
        }

    data = _prune(data)

    # Always include these structural fields
    data.setdefault("apiVersion", "initrunner/v1")
    data.setdefault("kind", "Agent")
    data.setdefault("metadata", {})["spec_version"] = 2

    # spec.role and spec.model are always required even if they matched defaults
    if "spec" in data:
        spec = data["spec"]
        spec.setdefault("role", role.spec.role)
        model_data = role.spec.model.model_dump(mode="json", exclude_none=True)
        spec.setdefault("model", model_data)

        # Capabilities: serialize NamedSpec back to YAML-native form.
        # model_dump produces {"name": "Thinking", "arguments": ("high",)}
        # but YAML expects "Thinking: high" or bare "Thinking".
        if role.spec.capabilities:
            yaml_caps = []
            for cap_spec in role.spec.capabilities:
                name = cap_spec.name
                args = cap_spec.arguments
                if args is None:
                    yaml_caps.append(name)
                elif isinstance(args, tuple) and len(args) == 1:
                    yaml_caps.append({name: args[0]})
                else:
                    yaml_caps.append({name: args})
            spec["capabilities"] = yaml_caps

    # Block-scalar representer for multiline strings
    class _BlockDumper(yaml.SafeDumper):
        pass

    def _str_representer(dumper: yaml.SafeDumper, data: str) -> yaml.ScalarNode:
        if "\n" in data:
            return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")
        return dumper.represent_scalar("tag:yaml.org,2002:str", data)

    _BlockDumper.add_representer(str, _str_representer)

    return yaml.dump(
        data,
        Dumper=_BlockDumper,
        default_flow_style=False,
        sort_keys=False,
        allow_unicode=True,
    )


def explain_role(role: RoleDefinition) -> list[tuple[str, str]]:
    """Return plain-language explanations for each present section of a role."""
    return [
        (name, text) for name, fn in _SECTION_EXPLAINERS.items() if (text := fn(role)) is not None
    ]


def _explain_role_prompt(role: RoleDefinition) -> str:
    prompt = role.spec.role
    if len(prompt) > 80:
        preview = prompt[:80].rsplit(" ", 1)[0] + "..."
    else:
        preview = prompt
    return f'The system prompt ({len(prompt)} chars) instructs the agent: "{preview}"'


def _explain_model(role: RoleDefinition) -> str:
    m = role.spec.model
    return (
        f"Uses {m.provider}:{m.name} with temperature {m.temperature} "
        f"and up to {m.max_tokens:,} output tokens."
    )


def _explain_output(role: RoleDefinition) -> str | None:
    out = role.spec.output
    if out.type == "text":
        return None
    source = "inline schema" if out.schema_ else f"schema file: {out.schema_file}"
    return (
        f"Structured output mode: the agent returns JSON conforming to a "
        f"json_schema definition ({source})."
    )


def _explain_tools(role: RoleDefinition) -> str | None:
    if not role.spec.tools:
        return None
    summaries = [f"  - {t.summary()}" for t in role.spec.tools]
    header = (
        f"{len(role.spec.tools)} tool(s) give the agent the ability to take actions "
        f"beyond generating text:"
    )
    return header + "\n" + "\n".join(summaries)


def _explain_skills(role: RoleDefinition) -> str | None:
    if not role.spec.skills:
        return None
    refs = ", ".join(role.spec.skills)
    return (
        f"Loads {len(role.spec.skills)} skill(s): {refs}\n"
        f"Skills are reusable prompt-and-tool bundles that add domain expertise."
    )


def _explain_capabilities(role: RoleDefinition) -> str | None:
    if not role.spec.capabilities:
        return None
    names = [c.name for c in role.spec.capabilities]
    return (
        f"Enables native model capabilities: {', '.join(names)}.\n"
        f"These are built into the model provider, not implemented as tools."
    )


def _explain_triggers(role: RoleDefinition) -> str | None:
    if not role.spec.triggers:
        return None
    summaries = [f"  - {tr.summary()}" for tr in role.spec.triggers]
    return (
        f"{len(role.spec.triggers)} trigger(s) make this agent event-driven "
        f"(runs automatically in response to external events):\n" + "\n".join(summaries)
    )


def _explain_sinks(role: RoleDefinition) -> str | None:
    if not role.spec.sinks:
        return None
    summaries = [f"  - {s.summary()}" for s in role.spec.sinks]
    return (
        f"{len(role.spec.sinks)} sink(s) forward the agent's output to external systems:\n"
        + "\n".join(summaries)
    )


def _explain_ingest(role: RoleDefinition) -> str | None:
    if not role.spec.ingest:
        return None
    ing = role.spec.ingest
    ch = ing.chunking
    return (
        f"Indexes documents from {len(ing.sources)} source(s) using "
        f"{ch.strategy} chunking ({ch.chunk_size}-char chunks, {ch.chunk_overlap}-char overlap).\n"
        f"This creates a searchable knowledge base (RAG) the agent queries at runtime."
    )


def _explain_memory(role: RoleDefinition) -> str | None:
    if not role.spec.memory:
        return None
    mem = role.spec.memory
    types = []
    if mem.episodic.enabled:
        types.append(f"episodic (up to {mem.episodic.max_episodes} episodes)")
    if mem.semantic.enabled:
        types.append(f"semantic (up to {mem.semantic.max_memories} memories)")
    if mem.procedural.enabled:
        types.append(f"procedural (up to {mem.procedural.max_procedures} procedures)")
    parts = [
        f"Gives the agent persistent memory across up to {mem.max_sessions} sessions.",
    ]
    if types:
        parts.append(f"Memory types: {', '.join(types)}.")
    if mem.consolidation.enabled:
        parts.append(
            f"Consolidation runs {mem.consolidation.interval}, "
            f"processing up to {mem.consolidation.max_episodes_per_run} episodes per run."
        )
    return "\n".join(parts)


def _explain_autonomy(role: RoleDefinition) -> str | None:
    if not role.spec.autonomy:
        return None
    return (
        "Enables autonomous multi-step execution. The agent iterates on its own, "
        "calling tools and evaluating progress without waiting for human input each step."
    )


def _explain_reasoning(role: RoleDefinition) -> str | None:
    if not role.spec.reasoning:
        return None
    r = role.spec.reasoning
    descriptions = {
        "react": "ReAct (interleaved reasoning and acting)",
        "todo_driven": "todo-driven (maintains a task list and works through it)",
        "plan_execute": "plan-then-execute (plans all steps first, then runs them)",
        "reflexion": "reflexion (iterates with self-critique to improve results)",
    }
    desc = descriptions.get(r.pattern, r.pattern)
    parts = [f"Uses the {desc} reasoning pattern."]
    if r.reflection_rounds:
        parts.append(f"Runs {r.reflection_rounds} reflection round(s) per step.")
    return " ".join(parts)


def _explain_guardrails(role: RoleDefinition) -> str | None:
    custom = role.spec.guardrails.model_dump(exclude_defaults=True)
    if not custom:
        return None
    g = role.spec.guardrails
    parts = [
        f"Safety limits: {g.max_tokens_per_run:,} tokens/run, "
        f"{g.max_tool_calls} tool calls, {g.timeout_seconds}s timeout."
    ]
    if g.session_token_budget is not None:
        parts.append(f"Session budget: {g.session_token_budget:,} tokens.")
    if g.daemon_token_budget is not None:
        parts.append(f"Daemon budget: {g.daemon_token_budget:,} tokens.")
    if g.daemon_daily_token_budget is not None:
        parts.append(f"Daily daemon budget: {g.daemon_daily_token_budget:,} tokens.")
    parts.append("These prevent runaway costs and infinite loops.")
    return " ".join(parts)


def _explain_security(role: RoleDefinition) -> str | None:
    custom = role.spec.security.model_dump(exclude_defaults=True)
    if not custom:
        return None
    sec = role.spec.security
    parts = []
    if sec.docker.enabled:
        parts.append(
            f"Docker sandbox: image={sec.docker.image}, "
            f"network={sec.docker.network}, memory={sec.docker.memory_limit}."
        )
    content_custom = sec.content.model_dump(exclude_defaults=True)
    if content_custom:
        details = []
        if sec.content.blocked_input_patterns:
            details.append(f"{len(sec.content.blocked_input_patterns)} blocked input pattern(s)")
        if sec.content.blocked_output_patterns:
            details.append(f"{len(sec.content.blocked_output_patterns)} blocked output pattern(s)")
        if sec.content.pii_redaction:
            details.append("PII redaction enabled")
        if details:
            parts.append(f"Content filtering: {', '.join(details)}.")
    tools_custom = sec.tools.model_dump(exclude_defaults=True)
    if tools_custom:
        details = []
        if sec.tools.allowed_write_paths:
            details.append(f"write restricted to {len(sec.tools.allowed_write_paths)} path(s)")
        if sec.tools.allowed_network_hosts:
            details.append(f"network restricted to {len(sec.tools.allowed_network_hosts)} host(s)")
        if sec.tools.allow_subprocess:
            details.append("subprocess allowed")
        if details:
            parts.append(f"Tool sandbox: {', '.join(details)}.")
    server_custom = sec.server.model_dump(exclude_defaults=True)
    if server_custom:
        details = []
        if sec.server.cors_origins:
            details.append(f"CORS: {len(sec.server.cors_origins)} origin(s)")
        if sec.server.require_https:
            details.append("HTTPS required")
        if details:
            parts.append(f"Server: {', '.join(details)}.")

    rl_custom = sec.rate_limit.model_dump(exclude_defaults=True)
    if rl_custom:
        parts.append(
            f"Rate limit: {sec.rate_limit.requests_per_minute} req/min, "
            f"burst {sec.rate_limit.burst_size}."
        )

    res_custom = sec.resources.model_dump(exclude_defaults=True)
    if res_custom:
        parts.append(
            f"Resource limits: {sec.resources.max_file_size_mb}MB max file, "
            f"{sec.resources.max_total_ingest_mb}MB max ingest."
        )

    audit_custom = sec.audit.model_dump(exclude_defaults=True)
    if audit_custom:
        parts.append(
            f"Audit: {sec.audit.max_records:,} max records, "
            f"{sec.audit.retention_days}-day retention."
        )

    if not parts:
        return None
    return "\n".join(parts)


def _explain_observability(role: RoleDefinition) -> str | None:
    if not role.spec.observability:
        return None
    obs = role.spec.observability
    return f"Sends traces to {obs.backend} at {obs.endpoint} (sample rate: {obs.sample_rate:.0%})."


def _explain_tool_search(role: RoleDefinition) -> str | None:
    if not role.spec.tool_search.enabled:
        return None
    ts = role.spec.tool_search
    parts = [
        "Tool search is enabled. The agent can dynamically discover and load tools "
        f"at runtime (up to {ts.max_results} results per search)."
    ]
    if ts.always_available:
        parts.append(f"Always available: {', '.join(ts.always_available)}.")
    return " ".join(parts)


def _explain_daemon(role: RoleDefinition) -> str | None:
    custom = role.spec.daemon.model_dump(exclude_defaults=True)
    if not custom:
        return None
    d = role.spec.daemon
    if d.hot_reload:
        return (
            f"Daemon mode: hot-reload enabled "
            f"(debounce {d.reload_debounce_seconds}s). "
            f"The agent restarts automatically when its role file changes."
        )
    return "Daemon mode: hot-reload disabled. Restart the daemon to pick up config changes."


_SECTION_EXPLAINERS: dict[str, _ExplainerFn] = {
    "Role": _explain_role_prompt,
    "Model": _explain_model,
    "Output": _explain_output,
    "Tools": _explain_tools,
    "Skills": _explain_skills,
    "Capabilities": _explain_capabilities,
    "Triggers": _explain_triggers,
    "Sinks": _explain_sinks,
    "Ingest": _explain_ingest,
    "Memory": _explain_memory,
    "Autonomy": _explain_autonomy,
    "Reasoning": _explain_reasoning,
    "Guardrails": _explain_guardrails,
    "Security": _explain_security,
    "Observability": _explain_observability,
    "Tool Search": _explain_tool_search,
    "Daemon": _explain_daemon,
}


def _detect_provider() -> str:
    """Auto-detect which provider has an API key available."""
    from initrunner.services.providers import detect_provider_and_model

    detected = detect_provider_and_model()
    if detected is not None:
        return detected.provider
    return "openai"
