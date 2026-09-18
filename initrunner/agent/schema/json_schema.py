"""JSON Schema for flat agent files, generated from the Pydantic models.

``schemas/agent.v3.json`` in the repository is this module's output. Editors
fetch it through the ``yaml-language-server`` directive that the builder puts
at the top of new agent files. Regenerate it with::

    initrunner schema > schemas/agent.v3.json

The schema covers structure: field names, types, enums, and the shorthand the
loader accepts. Rules that span fields (a ``then`` edge naming a real agent,
``prompt_cache`` only on Anthropic or Bedrock) stay with ``initrunner
validate``.
"""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic.json_schema import GenerateJsonSchema, JsonSchemaValue
from pydantic_core import core_schema

from initrunner.agent.schema.document import DocumentClass, classify_yaml_text
from initrunner.agent.schema.tools import ToolConfigBase
from initrunner.agent.schema.v3 import AgentDocument

SCHEMA_URL = "https://raw.githubusercontent.com/vladkesler/initrunner/main/schemas/agent.v3.json"
SCHEMA_DIRECTIVE = f"# yaml-language-server: $schema={SCHEMA_URL}"

_DIRECTIVE_RE = re.compile(r"^#\s*yaml-language-server:\s*\$schema=", re.MULTILINE)


class _AgentSchemaGenerator(GenerateJsonSchema):
    """Describes a ``tools`` entry as the loader reads it.

    The models type ``tools`` as ``ToolConfigBase`` and pick the concrete
    class from the tool registry at validation time, so the plain schema of
    that field lists only the base fields. Here it becomes every registered
    tool, in each form the loader accepts, plus the plugin fallback.
    """

    def model_schema(self, schema: core_schema.ModelSchema) -> JsonSchemaValue:
        if schema["cls"] is ToolConfigBase:
            return self._tool_entry_schema()
        return super().model_schema(schema)

    def _tool_entry_schema(self) -> JsonSchemaValue:
        from initrunner.agent.tools._registry import get_tool_types

        tool_types = get_tool_types()
        names = sorted(tool_types)
        refs = {
            name: self.generate_inner(tool_types[name].__pydantic_core_schema__) for name in names
        }
        # Pinning 'type' to the registry name keeps a loose model (the
        # 'plugin' tool's type is any string) from accepting another tool.
        typed = [
            {"allOf": [refs[name]], "properties": {"type": {"const": name}}, "required": ["type"]}
            for name in names
        ]
        single_key = {
            "type": "object",
            "minProperties": 1,
            "maxProperties": 1,
            "not": {"required": ["type"]},
            "properties": {name: {"anyOf": [refs[name], {"type": "null"}]} for name in names},
            "additionalProperties": {"type": ["object", "null"]},
        }
        plugin = {
            "type": "object",
            "required": ["type"],
            "properties": {"type": {"type": "string", "not": {"enum": names}}},
        }
        return {
            "title": "Tool",
            "description": (
                "A tool name ('think'), a single-key mapping ({shell: {...}}), or a "
                "mapping with 'type'. Names that are not built in are plugin tools, "
                "and their other keys are passed to the plugin."
            ),
            "anyOf": [{"type": "string"}, *typed, single_key, plugin],
        }


def build_agent_schema() -> dict[str, Any]:
    """The agent-file JSON Schema (draft 2020-12) as a dict."""
    schema = AgentDocument.model_json_schema(
        mode="validation", schema_generator=_AgentSchemaGenerator
    )
    body = {key: value for key, value in schema.items() if key not in ("title", "description")}
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": SCHEMA_URL,
        "title": "InitRunner agent",
        "description": (
            "An InitRunner agent file (spec_version 3). Checks that span fields "
            "run in `initrunner validate`."
        ),
        **body,
    }


def render_agent_schema() -> str:
    """The schema as the text of ``schemas/agent.v3.json``."""
    return json.dumps(build_agent_schema(), indent=2, ensure_ascii=False) + "\n"


def with_schema_directive(text: str) -> str:
    """Put the editor schema directive on the first line of a flat agent file.

    Text that already names a schema (any ``$schema=`` directive, a local
    file included) comes back unchanged, and so does anything that is not a
    flat agent document, because the schema describes only that format.
    """
    if _DIRECTIVE_RE.search(text):
        return text
    if classify_yaml_text(text).document_class is not DocumentClass.FLAT_AGENT:
        return text
    return f"{SCHEMA_DIRECTIVE}\n{text}"
