"""Role generation, YAML persistence, and provider detection."""

from __future__ import annotations

import os
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

    from initrunner.agent.schema.role import RoleDefinition as RoleDef

    # Parse and validate first
    try:
        raw = yaml.safe_load(yaml_content)
    except yaml.YAMLError as e:
        raise ValueError(f"Invalid YAML syntax: {e}") from e

    if not isinstance(raw, dict):
        raise ValueError("YAML must be a mapping")

    role = RoleDef.model_validate(raw)

    # Backup existing file before overwrite
    if path.exists():
        bak_path = path.with_suffix(path.suffix + ".bak")
        bak_path.write_text(path.read_text())

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml_content)
    return role


def build_role_yaml_sync(
    *,
    name: str,
    description: str = "",
    provider: str = "openai",
    model_name: str | None = None,
    system_prompt: str = "You are a helpful assistant.",
    tools: list[dict] | None = None,
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
        memory=memory,
        ingest=ingest,
        triggers=triggers,
        sinks=sinks,
    )


def _detect_provider() -> str:
    """Auto-detect which provider has an API key available."""
    from initrunner.agent.loader import _PROVIDER_API_KEY_ENVS

    for prov, env_var in _PROVIDER_API_KEY_ENVS.items():
        if os.environ.get(env_var):
            return prov
    return "openai"
