"""Role generation, YAML persistence, and provider detection."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from initrunner.agent.schema.role import RoleDefinition


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


def _detect_provider() -> str:
    """Auto-detect which provider has an API key available."""
    from initrunner.services.providers import detect_provider_and_model

    detected = detect_provider_and_model()
    if detected is not None:
        return detected.provider
    return "openai"
