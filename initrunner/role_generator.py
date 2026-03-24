"""LLM-based role.yaml generation from natural language descriptions."""

from __future__ import annotations

import logging

import yaml
from pydantic import BaseModel
from pydantic_core import PydanticUndefined

_logger = logging.getLogger(__name__)


def _format_model_fields(prefix: str, cls: type[BaseModel]) -> str:
    """Format a Pydantic model's fields as compact 'field: default' lines."""
    lines = [f"{prefix}:"]
    for name, info in cls.model_fields.items():
        if name == "type":
            continue
        annotation = info.annotation
        type_hint = getattr(annotation, "__name__", str(annotation))
        if info.default is not PydanticUndefined:
            lines.append(f"  {name}: {info.default!r}  # {type_hint}")
        else:
            lines.append(f"  {name}: (required)  # {type_hint}")
    return "\n".join(lines)


def build_schema_reference() -> str:
    """Generate compact YAML schema reference from Pydantic models.

    Dynamically introspects the actual schema models so the AI prompt
    always stays in sync with the code. Returns ~2-3K tokens of terse
    reference text.
    """
    from initrunner.agent.schema.base import Metadata, ModelConfig
    from initrunner.agent.schema.guardrails import Guardrails
    from initrunner.agent.schema.ingestion import ChunkingConfig, EmbeddingConfig, IngestConfig
    from initrunner.agent.schema.memory import MemoryConfig
    from initrunner.agent.schema.role import AgentSpec
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

    sections: list[str] = []

    # Fixed preamble
    sections.append("# Role YAML structure\napiVersion: initrunner/v1\nkind: Agent")

    # Metadata
    sections.append(_format_model_fields("metadata", Metadata))
    sections.append("# metadata.spec_version: 2  # required for new roles")

    # Model config
    sections.append(_format_model_fields("spec.model", ModelConfig))

    # Guardrails
    sections.append(_format_model_fields("spec.guardrails", Guardrails))

    # Tool types from registry
    tool_types = get_tool_types()
    tool_lines = ["# Available tool types (spec.tools list):"]
    for type_name, config_cls in sorted(tool_types.items()):
        fields = []
        for fname, finfo in config_cls.model_fields.items():
            if fname == "type":
                continue
            if finfo.default is not PydanticUndefined:
                fields.append(f"{fname}={finfo.default!r}")
            else:
                fields.append(f"{fname}=(required)")
        tool_lines.append(f"- type: {type_name}  # {', '.join(fields)}")
    sections.append("\n".join(tool_lines))

    # Also include ToolConfigBase subclasses not in registry (schema-only)
    schema_tool_types = set()
    for subcls in ToolConfigBase.__subclasses__():
        type_field = subcls.model_fields.get("type")
        if type_field and type_field.default is not PydanticUndefined:
            t = type_field.default
            if t not in tool_types:
                schema_tool_types.add(t)
                fields = []
                for fname, finfo in subcls.model_fields.items():
                    if fname == "type":
                        continue
                    if finfo.default is not PydanticUndefined:
                        fields.append(f"{fname}={finfo.default!r}")
                    else:
                        fields.append(f"{fname}=(required)")
                tool_lines.append(f"- type: {t}  # {', '.join(fields)}")

    # Triggers
    trigger_lines = ["# Trigger types (spec.triggers list):"]
    for cls in [
        CronTriggerConfig,
        FileWatchTriggerConfig,
        WebhookTriggerConfig,
        TelegramTriggerConfig,
        DiscordTriggerConfig,
    ]:
        type_field = cls.model_fields.get("type")
        type_name = type_field.default if type_field else "?"
        fields = []
        for fname, finfo in cls.model_fields.items():
            if fname == "type":
                continue
            if finfo.default is not PydanticUndefined:
                fields.append(f"{fname}={finfo.default!r}")
            else:
                fields.append(f"{fname}=(required)")
        trigger_lines.append(f"- type: {type_name}  # {', '.join(fields)}")
    sections.append("\n".join(trigger_lines))

    # Sinks
    sink_lines = ["# Sink types (spec.sinks list):"]
    for cls in [WebhookSinkConfig, FileSinkConfig, CustomSinkConfig]:
        type_field = cls.model_fields.get("type")
        type_name = type_field.default if type_field else "?"
        fields = []
        for fname, finfo in cls.model_fields.items():
            if fname == "type":
                continue
            if finfo.default is not PydanticUndefined:
                fields.append(f"{fname}={finfo.default!r}")
            else:
                fields.append(f"{fname}=(required)")
        sink_lines.append(f"- type: {type_name}  # {', '.join(fields)}")
    sections.append("\n".join(sink_lines))

    # Ingest
    sections.append(_format_model_fields("spec.ingest", IngestConfig))
    sections.append(_format_model_fields("spec.ingest.chunking", ChunkingConfig))
    sections.append(_format_model_fields("spec.ingest.embeddings", EmbeddingConfig))

    # Memory
    sections.append(_format_model_fields("spec.memory", MemoryConfig))

    # Reasoning
    from initrunner.agent.schema.autonomy import AutonomyConfig, CompactionConfig
    from initrunner.agent.schema.reasoning import ReasoningConfig

    sections.append(_format_model_fields("spec.reasoning", ReasoningConfig))
    sections.append(_format_model_fields("spec.autonomy", AutonomyConfig))
    sections.append(_format_model_fields("spec.autonomy.compaction", CompactionConfig))
    sections.append(
        "# Reasoning advisory:\n"
        "# - react is the default; no extra config needed\n"
        "# - reasoning strategies are meant for autonomous runs (initrunner run -a)\n"
        "# - todo_driven and plan_execute require type: todo in tools; type: think is recommended\n"
        "# - reflexion needs reflection_rounds > 0; think with critique: true recommended\n"
        "# - an explicit spec.autonomy block is recommended for non-react patterns\n"
        "#   so continuation behavior and limits are visible in generated YAML\n"
        "# - spec.autonomy.compaction keeps context manageable during long autonomous runs"
    )

    # Spec fields overview
    spec_lines = ["# spec top-level fields:"]
    for fname, finfo in AgentSpec.model_fields.items():
        if fname in ("model", "guardrails", "resources", "security"):
            continue
        if finfo.default is not PydanticUndefined:
            spec_lines.append(f"  {fname}: {finfo.default!r}")
        else:
            spec_lines.append(f"  {fname}: (required)")
    sections.append("\n".join(spec_lines))

    return "\n\n".join(sections)


def build_tool_summary() -> str:
    """Generate a concise tool summary from the live tool registry."""
    from initrunner.agent.tools._registry import get_tool_types

    tool_types = get_tool_types()
    lines = ["# Available tools (use in spec.tools list):"]
    for type_name, config_cls in sorted(tool_types.items()):
        desc_parts = []
        for fname, finfo in config_cls.model_fields.items():
            if fname in ("type", "permissions"):
                continue
            if finfo.default is not PydanticUndefined:
                desc_parts.append(f"{fname}={finfo.default!r}")
            else:
                desc_parts.append(f"{fname}=(required)")
        lines.append(f"- type: {type_name}  # {', '.join(desc_parts)}")
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
