"""LLM-based role.yaml generation from natural language descriptions."""

from __future__ import annotations

import logging

import yaml
from pydantic import BaseModel
from pydantic_core import PydanticUndefined

_logger = logging.getLogger(__name__)


def _format_model_fields(heading: str, cls: type[BaseModel]) -> str:
    """Format a Pydantic model's fields: required fields shown, optional names only."""
    required = []
    optional = []
    for name, info in cls.model_fields.items():
        if name == "type":
            continue
        if info.default is PydanticUndefined:
            required.append(name)
        else:
            optional.append(name)
    lines = [f"# {heading}"]
    if required:
        lines.append(f"#   Required: {', '.join(required)}")
    if optional:
        lines.append(f"#   Optional (omit for defaults): {', '.join(optional)}")
    return "\n".join(lines)


def build_schema_reference() -> str:
    """Generate compact YAML schema reference from Pydantic models.

    Dynamically introspects the actual schema models so the AI prompt
    always stays in sync with the code. Returns ~2-3K tokens of terse
    reference text.
    """
    from initrunner.agent.schema.base import ModelConfig
    from initrunner.agent.schema.guardrails import Guardrails
    from initrunner.agent.schema.sinks import CustomSinkConfig, FileSinkConfig, WebhookSinkConfig
    from initrunner.agent.schema.tools import ToolConfigBase
    from initrunner.agent.schema.triggers import (
        CronTriggerConfig,
        DiscordTriggerConfig,
        FileWatchTriggerConfig,
        TelegramTriggerConfig,
        WebhookTriggerConfig,
    )
    from initrunner.agent.tools._registry import get_tool_types

    def _typed_items(heading: str, items: list[tuple[str, type[BaseModel]]]) -> str:
        """Format typed config items showing only required params."""
        lines = [f"# {heading}"]
        for type_name, cls in items:
            required = [
                n
                for n, f in cls.model_fields.items()
                if n not in ("type", "permissions") and f.default is PydanticUndefined
            ]
            if required:
                lines.append(f"#   - type: {type_name}  ({', '.join(required)} required)")
            else:
                lines.append(f"#   - type: {type_name}")
        return "\n".join(lines)

    sections: list[str] = []

    # Structure
    sections.append(
        "# Role YAML structure\n"
        "# apiVersion: initrunner/v1\n"
        "# kind: Agent\n"
        "# metadata: name (required), description, tags, spec_version: 2\n"
        "# spec: role (required), model (required), plus optional sections below"
    )

    # Model config
    sections.append(_format_model_fields("Model (spec.model)", ModelConfig))

    # Guardrails
    sections.append(_format_model_fields("Guardrails (spec.guardrails)", Guardrails))

    # Tool types from registry
    tool_types = get_tool_types()
    tool_items: list[tuple[str, type[BaseModel]]] = [
        (name, cls) for name, cls in sorted(tool_types.items())
    ]
    for subcls in ToolConfigBase.__subclasses__():
        type_field = subcls.model_fields.get("type")
        if type_field and type_field.default is not PydanticUndefined:
            t = type_field.default
            if t not in tool_types:
                tool_items.append((t, subcls))
    sections.append(_typed_items("Tools (spec.tools list)", tool_items))

    # Capabilities (PydanticAI native)
    cap_lines = [
        "# Capabilities (spec.capabilities list):",
        "# Syntax: bare string, single-value dict, or kwargs dict",
        "#   - WebSearch                     # no args",
        "#   - Thinking: high               # single arg (effort level)",
        "#   - MCP: {url: https://...}      # kwargs",
        "# Available: Thinking, WebSearch, WebFetch, ImageGeneration,",
        "#   MCP, BuiltinTool, PrefixTools",
        "# NEVER declare both a capability and its equivalent tool.",
        "# Prefer: WebSearch cap over search tool, web_reader tool over WebFetch cap.",
        "#   WebSearch conflicts with type: search",
        "#   WebFetch conflicts with type: web_reader",
        "#   ImageGeneration conflicts with type: image_gen",
    ]
    sections.append("\n".join(cap_lines))

    # Triggers
    trigger_items = []
    for cls in [
        CronTriggerConfig,
        FileWatchTriggerConfig,
        WebhookTriggerConfig,
        TelegramTriggerConfig,
        DiscordTriggerConfig,
    ]:
        type_field = cls.model_fields.get("type")
        type_name = type_field.default if type_field else "?"
        trigger_items.append((type_name, cls))
    sections.append(_typed_items("Triggers (spec.triggers list)", trigger_items))

    # Sinks
    sink_items = []
    for cls in [WebhookSinkConfig, FileSinkConfig, CustomSinkConfig]:
        type_field = cls.model_fields.get("type")
        type_name = type_field.default if type_field else "?"
        sink_items.append((type_name, cls))
    sections.append(_typed_items("Sinks (spec.sinks list)", sink_items))

    # Optional sections (names only, no field details)
    sections.append(
        "# Optional spec sections (include only if needed):\n"
        "#   spec.ingest -- RAG document ingestion (sources, chunking, embeddings)\n"
        "#   spec.memory -- episodic, semantic, procedural memory\n"
        "#   spec.reasoning -- pattern: react|reflexion|todo_driven|plan_execute\n"
        "#   spec.autonomy -- continuation behavior for long-running agents\n"
        "#   spec.security -- content policy, sandbox, auth\n"
        "#   spec.observability -- OpenTelemetry tracing\n"
        "# Omit sections that use defaults. The output will be minimized automatically."
    )

    return "\n\n".join(sections)


def build_tool_summary() -> str:
    """Generate a concise tool summary showing only required params."""
    from initrunner.agent.tools._registry import get_tool_types

    tool_types = get_tool_types()
    lines = ["# Tools: only include fields that differ from defaults."]
    for type_name, config_cls in sorted(tool_types.items()):
        required = [
            n
            for n, f in config_cls.model_fields.items()
            if n not in ("type", "permissions") and f.default is PydanticUndefined
        ]
        if required:
            lines.append(f"# - type: {type_name}  ({', '.join(required)} required)")
        else:
            lines.append(f"# - type: {type_name}")
    return "\n".join(lines)


def _strip_yaml_fences(text: str) -> str:
    """Remove markdown code fences wrapping YAML content."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)
    return text


def _validate_yaml(text: str) -> tuple[bool, str]:
    """Validate YAML text against RoleDefinition. Returns (valid, error_msg)."""
    from initrunner.deprecations import validate_role_dict

    try:
        raw = yaml.safe_load(text)
        validate_role_dict(raw)
        return True, ""
    except Exception as e:
        return False, str(e)


def generate_role(
    description: str,
    *,
    provider: str = "openai",
    model_name: str | None = None,
    name_hint: str | None = None,
) -> str:
    """Generate role YAML from a natural language description using an LLM.

    One-shot generation implemented via BuilderSession.
    """
    from initrunner.services.agent_builder import BuilderSession

    session = BuilderSession()
    turn = session.seed_description(
        description,
        provider=provider,
        model_name=model_name,
        name_hint=name_hint,
    )
    return turn.yaml_text
