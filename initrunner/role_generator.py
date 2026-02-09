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
    from initrunner.agent.schema import (
        AgentSpec,
        ChunkingConfig,
        CronTriggerConfig,
        CustomSinkConfig,
        EmbeddingConfig,
        FileSinkConfig,
        FileWatchTriggerConfig,
        Guardrails,
        IngestConfig,
        MemoryConfig,
        Metadata,
        ModelConfig,
        ToolConfigBase,
        WebhookSinkConfig,
        WebhookTriggerConfig,
    )
    from initrunner.agent.tools._registry import get_tool_types

    sections: list[str] = []

    # Fixed preamble
    sections.append("# Role YAML structure\napiVersion: initrunner/v1\nkind: Agent")

    # Metadata
    sections.append(_format_model_fields("metadata", Metadata))

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
    for cls in [CronTriggerConfig, FileWatchTriggerConfig, WebhookTriggerConfig]:
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


_SYSTEM_PROMPT = """\
You are an expert at creating InitRunner agent role YAML configuration files.

Given a natural language description, produce a valid role.yaml file.

Rules:
- Output ONLY valid YAML, no markdown fences, no explanation.
- Use apiVersion: initrunner/v1 and kind: Agent.
- metadata.name must match ^[a-z0-9][a-z0-9-]*[a-z0-9]$ (lowercase, hyphens only).
- Pick appropriate tools, triggers, and features based on the description.
- Use sensible defaults for guardrails.
- The spec.role field is the system prompt — write a good one that matches the description.
- For tool configs, only include fields that differ from defaults.
- Keep YAML clean and minimal.
- Only include sections the agent actually needs. A simple chatbot needs no tools,
  triggers, sinks, or ingest.
- CRITICAL: The schema reference below uses dotted paths like "spec.model" for readability.
  In the actual YAML, these MUST be nested under their parent key, NOT used as flat dotted keys.
  Correct: spec: \\n  model: \\n    provider: openai
  Wrong:   spec.model: \\n  provider: openai

Example minimal role.yaml:
```
apiVersion: initrunner/v1
kind: Agent
metadata:
  name: my-agent
  description: A helpful assistant.
spec:
  role: You are a helpful assistant.
  model:
    provider: openai
    name: gpt-4o-mini
  guardrails:
    timeout_seconds: 30
```

{schema_reference}
"""


def generate_role(
    description: str,
    *,
    provider: str = "openai",
    model_name: str | None = None,
    name_hint: str | None = None,
) -> str:
    """Generate role YAML from a natural language description using an LLM.

    Returns the generated YAML string. Validates via RoleDefinition
    and retries once if invalid.
    """
    from pydantic_ai import Agent

    from initrunner.agent.loader import _build_model
    from initrunner.agent.schema import ModelConfig, RoleDefinition
    from initrunner.templates import _default_model_name

    if model_name is None:
        model_name = _default_model_name(provider)

    schema_ref = build_schema_reference()
    system = _SYSTEM_PROMPT.format(schema_reference=schema_ref)

    user_prompt = f"Create a role.yaml for: {description}"
    if name_hint:
        user_prompt += f"\nUse the name: {name_hint}"

    # Build model config for the generator itself
    gen_model_config = ModelConfig(provider=provider, name=model_name)
    model = _build_model(gen_model_config)

    agent: Agent[None, str] = Agent(model, system_prompt=system)

    result = agent.run_sync(user_prompt)
    yaml_text = result.output.strip()

    # Strip markdown fences if present
    if yaml_text.startswith("```"):
        lines = yaml_text.split("\n")
        # Remove first and last lines if they are fences
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        yaml_text = "\n".join(lines)

    # Validate
    def _try_validate(text: str) -> tuple[bool, str]:
        try:
            raw = yaml.safe_load(text)
            RoleDefinition.model_validate(raw)
            return True, ""
        except Exception as e:
            return False, str(e)

    valid, error = _try_validate(yaml_text)
    if not valid:
        # Retry once with the error appended
        _logger.info("Generated YAML invalid, retrying: %s", error)
        retry_prompt = (
            f"The YAML you generated had a validation error:\n{error}\n\n"
            f"Fix the issue and output the corrected YAML only."
        )
        retry_result = agent.run_sync(
            retry_prompt,
            message_history=result.all_messages(),
        )
        yaml_text = retry_result.output.strip()
        if yaml_text.startswith("```"):
            lines = yaml_text.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            yaml_text = "\n".join(lines)

    return yaml_text
