"""Convert JSON Schema dicts into dynamic Pydantic models for structured agent output."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, create_model

from initrunner.agent.schema import OutputConfig

# JSON Schema type string → Python type
_JS_TYPE_MAP: dict[str, type] = {
    "string": str,
    "number": float,
    "integer": int,
    "boolean": bool,
}


def _build_field_type(
    prop_schema: dict[str, Any],
    field_name: str,
    parent_name: str,
) -> type:
    """Resolve a single JSON Schema property to a Python type."""
    js_type = prop_schema.get("type", "string")

    if js_type == "string" and "enum" in prop_schema:
        from typing import Literal

        values = tuple(prop_schema["enum"])
        return Literal[values]  # type: ignore[valid-type]

    if js_type == "object":
        nested_name = f"{parent_name}_{field_name.title()}"
        return build_output_model(prop_schema, model_name=nested_name)

    if js_type == "array":
        items_schema = prop_schema.get("items", {"type": "string"})
        item_type = _build_field_type(items_schema, f"{field_name}_item", parent_name)
        return list[item_type]  # type: ignore[valid-type]

    return _JS_TYPE_MAP.get(js_type, str)


def build_output_model(
    schema: dict[str, Any],
    model_name: str = "AgentOutput",
) -> type[BaseModel]:
    """Convert a JSON Schema dict into a dynamic Pydantic BaseModel subclass.

    The root schema must be ``type: object``. Non-object roots (e.g.
    ``type: string``) raise ``ValueError`` — use ``type: text`` output for those.

    Supported JSON Schema subset:
    - Primitive types: string, number, integer, boolean
    - string with enum → Literal[...]
    - object with properties → nested create_model()
    - array with items → list[ItemType]
    - required list → required fields; absent → Optional with None default
    - description → Field(description=...)
    """
    root_type = schema.get("type", "object")
    if root_type != "object":
        raise ValueError(
            f"Root schema must be type: object, got type: {root_type}. "
            "Use output type: text for non-object outputs."
        )

    properties = schema.get("properties", {})
    required_fields = set(schema.get("required", []))

    field_definitions: dict[str, Any] = {}
    for prop_name, prop_schema in properties.items():
        field_type = _build_field_type(prop_schema, prop_name, model_name)
        description = prop_schema.get("description")

        if prop_name in required_fields:
            if description:
                field_definitions[prop_name] = (field_type, Field(description=description))
            else:
                field_definitions[prop_name] = (field_type, ...)
        else:
            optional_type = field_type | None
            if description:
                field_definitions[prop_name] = (
                    optional_type,
                    Field(default=None, description=description),
                )
            else:
                field_definitions[prop_name] = (optional_type, None)

    return create_model(model_name, **field_definitions)


def resolve_output_type(
    output_config: OutputConfig,
    role_dir: Path | None = None,
) -> type:
    """Resolve an OutputConfig to a Python type for PydanticAI's ``output_type`` param.

    Returns ``str`` for text output, or a dynamic ``BaseModel`` subclass for
    ``json_schema`` output.
    """
    if output_config.type == "text":
        return str

    # json_schema — get the schema dict
    if output_config.schema_ is not None:
        schema = output_config.schema_
    else:
        # schema_file
        schema_path = Path(output_config.schema_file)  # type: ignore[arg-type]
        if role_dir is not None and not schema_path.is_absolute():
            schema_path = role_dir / schema_path
        raw = schema_path.read_text(encoding="utf-8")
        schema = json.loads(raw)

    return build_output_model(schema)
