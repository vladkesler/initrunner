"""PydanticAI Agent Spec -> InitRunner role.yaml converter.

Deterministic dict-based mapping.  Does NOT route through
``pydantic_ai.agent.spec.AgentSpec.model_validate`` because that pulls
``pydantic-handlebars`` for templated instructions; we have our own renderer
(see ``initrunner.agent.templating``).

Supported fields (mapped verbatim): ``model``, ``name``, ``description``,
``instructions``, ``model_settings.{max_tokens,temperature}``, ``capabilities``,
``retries``, ``output_retries``, ``end_strategy``, ``tool_timeout``,
``deps_schema``, ``output_schema``, ``metadata``.

Ignored (with a warning): ``json_schema_path``, ``instrument``.  The latter is
silently ignored -- InitRunner has its own ``spec.observability`` and wiring
PydanticAI's flag through would collide.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from initrunner._yaml import load_raw_yaml
from initrunner.agent.schema.base import _split_provider_and_name


class AgentSpecImportError(Exception):
    """Raised when an agent-spec YAML file cannot be mapped to a role."""


_VALID_END_STRATEGIES = {"early", "graceful", "exhaustive"}


def _coerce_instructions(value: Any) -> str:
    """Collapse a list of instructions into a single string (newline-joined)."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n\n".join(str(item) for item in value if item)
    raise AgentSpecImportError(
        f"'instructions' must be a string or list of strings, got {type(value).__name__}"
    )


def _resolve_name(spec: dict[str, Any], fallback_stem: str) -> str:
    """Name precedence: spec.name -> spec.metadata['name'] -> filename stem."""
    if isinstance(spec.get("name"), str) and spec["name"]:
        return spec["name"]
    metadata = spec.get("metadata")
    if isinstance(metadata, dict):
        meta_name = metadata.get("name")
        if isinstance(meta_name, str) and meta_name:
            return meta_name
    return fallback_stem


def agent_spec_to_role_dict(spec: dict[str, Any], *, fallback_name: str) -> dict[str, Any]:
    """Convert a PydanticAI AgentSpec dict to an InitRunner role dict.

    Returned dict is suitable for ``yaml.safe_dump`` and for feeding
    ``validate_role_dict`` / ``load_role``.  Warnings (as a list of strings)
    are attached under the ``_import_warnings`` private key so callers can
    surface them without threading a second return value through every layer.
    """
    if not isinstance(spec, dict):
        raise AgentSpecImportError(
            f"Top-level agent-spec must be a mapping, got {type(spec).__name__}"
        )

    warnings: list[str] = []

    # --- metadata -----------------------------------------------------------
    metadata: dict[str, Any] = {"name": _resolve_name(spec, fallback_name)}
    description = spec.get("description")
    if isinstance(description, str) and description:
        metadata["description"] = description

    # AgentSpec.metadata is free-form; lift the keys our Metadata schema knows.
    spec_metadata = spec.get("metadata")
    if isinstance(spec_metadata, dict):
        if isinstance(spec_metadata.get("tags"), list):
            metadata["tags"] = [str(t) for t in spec_metadata["tags"]]
        for key in ("author", "team", "version"):
            value = spec_metadata.get(key)
            if isinstance(value, str) and value:
                metadata[key] = value
        leftover = sorted(set(spec_metadata) - {"name", "tags", "author", "team", "version"})
        if leftover:
            warnings.append(
                f"Dropped unrecognized metadata keys: {leftover}. "
                f"InitRunner role metadata supports tags, author, team, version."
            )

    # --- model --------------------------------------------------------------
    model_str = spec.get("model")
    if not isinstance(model_str, str) or not model_str:
        raise AgentSpecImportError("'model' is required and must be a 'provider:name' string")
    provider, name = _split_provider_and_name(model_str)
    if not provider:
        raise AgentSpecImportError(
            f"Could not resolve model '{model_str}'. Use 'provider:name' "
            f"or add an alias to ~/.initrunner/models.yaml."
        )
    model_block: dict[str, Any] = {"provider": provider, "name": name}

    model_settings = spec.get("model_settings") or {}
    if isinstance(model_settings, dict):
        if "max_tokens" in model_settings:
            model_block["max_tokens"] = model_settings["max_tokens"]
        if "temperature" in model_settings:
            model_block["temperature"] = model_settings["temperature"]
        # Any other model_settings keys are dropped with a warning
        leftover = [k for k in model_settings if k not in {"max_tokens", "temperature"}]
        if leftover:
            warnings.append(
                f"Dropped unsupported model_settings keys: {sorted(leftover)}. "
                f"Use InitRunner's spec.capabilities / spec.guardrails instead."
            )

    # --- spec ---------------------------------------------------------------
    role_spec: dict[str, Any] = {
        "role": _coerce_instructions(spec.get("instructions")),
        "model": model_block,
    }

    # Capabilities -- PydanticAI NamedSpec format; we accept it verbatim
    capabilities = spec.get("capabilities")
    if isinstance(capabilities, list) and capabilities:
        role_spec["capabilities"] = capabilities

    # Execution fields
    execution: dict[str, Any] = {}
    if "retries" in spec:
        execution["retries"] = spec["retries"]
    if "output_retries" in spec and spec["output_retries"] is not None:
        execution["output_retries"] = spec["output_retries"]
    if "end_strategy" in spec:
        end_strategy = spec["end_strategy"]
        if end_strategy not in _VALID_END_STRATEGIES:
            raise AgentSpecImportError(
                f"end_strategy must be one of {sorted(_VALID_END_STRATEGIES)}, got {end_strategy!r}"
            )
        execution["end_strategy"] = end_strategy
    if "tool_timeout" in spec and spec["tool_timeout"] is not None:
        execution["tool_timeout_seconds"] = spec["tool_timeout"]
    if execution:
        role_spec["execution"] = execution

    # deps_schema -- verbatim; runtime binding validation happens in Commit 3
    deps_schema = spec.get("deps_schema")
    if deps_schema is not None:
        if not isinstance(deps_schema, dict):
            raise AgentSpecImportError("'deps_schema' must be a mapping (JSON Schema)")
        role_spec["deps_schema"] = deps_schema

    # output_schema -> role.spec.output
    output_schema = spec.get("output_schema")
    if output_schema is not None:
        if not isinstance(output_schema, dict):
            raise AgentSpecImportError("'output_schema' must be a mapping (JSON Schema)")
        role_spec["output"] = {"type": "json_schema", "schema": output_schema}

    # Things we deliberately ignore -- warn if user supplied them
    if spec.get("instrument") is not None:
        warnings.append(
            "Dropped 'instrument' -- use InitRunner's spec.observability to configure telemetry."
        )
    if spec.get("json_schema_path") is not None:
        warnings.append(
            "Dropped 'json_schema_path' -- InitRunner does not need the companion schema path."
        )

    role_dict: dict[str, Any] = {
        "apiVersion": "initrunner/v1",
        "kind": "Agent",
        "metadata": metadata,
        "spec": role_spec,
    }
    if warnings:
        role_dict["_import_warnings"] = warnings
    return role_dict


def load_agent_spec(path: Path) -> dict[str, Any]:
    """Load an agent-spec YAML file and return an InitRunner role dict.

    The returned dict carries ``_import_warnings`` when non-fatal fields were
    dropped; callers should pop this before serializing back to YAML.
    """
    try:
        raw = load_raw_yaml(path, AgentSpecImportError)
    except AgentSpecImportError:
        raise
    fallback = path.stem or "agent"
    return agent_spec_to_role_dict(raw, fallback_name=fallback)
