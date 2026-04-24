"""InitRunner role.yaml -> PydanticAI Agent Spec converter.

Emits only the overlap fields between our ``RoleDefinition`` schema and
PydanticAI's ``AgentSpec``.  Fields like triggers, ingest, memory, skills,
sinks, autonomy, reasoning, guardrails, resources, security, and observability
have no Agent-Spec analogue and are dropped -- the caller gets a
``DroppedSections`` summary so the CLI can show a warning.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from initrunner.agent.schema.role import RoleDefinition


@dataclass
class DroppedSections:
    """Per-section drop record for the CLI warning table."""

    names: list[str] = field(default_factory=list)

    def add(self, name: str) -> None:
        self.names.append(name)


def role_to_agent_spec(role: RoleDefinition) -> tuple[dict[str, Any], DroppedSections]:
    """Convert a ``RoleDefinition`` to an AgentSpec dict + dropped-section report.

    The returned dict is ready for ``yaml.safe_dump`` and validates cleanly
    against ``pydantic_ai.agent.spec.AgentSpec`` (modulo handlebars for
    templated instructions, which is an optional-extra concern).
    """
    spec: dict[str, Any] = {}
    dropped = DroppedSections()

    # --- identity -----------------------------------------------------------
    spec["name"] = role.metadata.name
    if role.metadata.description:
        spec["description"] = role.metadata.description

    # --- model --------------------------------------------------------------
    model = role.spec.model
    if model is None or not getattr(model, "provider", "") or not getattr(model, "name", ""):
        raise ValueError("role.spec.model must be resolved to export; got empty provider/name")
    spec["model"] = f"{model.provider}:{model.name}"

    model_settings: dict[str, Any] = {}
    if model.max_tokens:
        model_settings["max_tokens"] = model.max_tokens
    model_settings["temperature"] = model.temperature
    spec["model_settings"] = model_settings

    if model.fallback:
        dropped.add("model.fallback")

    # --- instructions -------------------------------------------------------
    if role.spec.role:
        spec["instructions"] = role.spec.role

    # --- capabilities (NamedSpec, same format) ------------------------------
    if role.spec.capabilities:
        caps_dump: list[Any] = []
        for cap in role.spec.capabilities:
            if hasattr(cap, "model_dump"):
                caps_dump.append(cap.model_dump(exclude_none=True))
            else:
                caps_dump.append(cap)
        spec["capabilities"] = caps_dump

    # --- execution ----------------------------------------------------------
    execution = role.spec.execution
    if execution.retries != 1:
        spec["retries"] = execution.retries
    if execution.output_retries is not None:
        spec["output_retries"] = execution.output_retries
    if execution.end_strategy != "early":
        spec["end_strategy"] = execution.end_strategy
    if execution.tool_timeout_seconds is not None:
        spec["tool_timeout"] = execution.tool_timeout_seconds

    # --- deps_schema / output_schema ---------------------------------------
    deps_schema = getattr(role.spec, "deps_schema", None)
    if deps_schema is not None:
        spec["deps_schema"] = deps_schema

    output = role.spec.output
    if output.type == "json_schema" and getattr(output, "schema_", None):
        spec["output_schema"] = output.schema_

    # --- record dropped InitRunner-only sections ---------------------------
    if role.spec.tools:
        dropped.add("tools")
    if role.spec.triggers:
        dropped.add("triggers")
    if role.spec.sinks:
        dropped.add("sinks")
    if role.spec.skills:
        dropped.add("skills")
    if role.spec.ingest is not None:
        dropped.add("ingest")
    if role.spec.memory is not None:
        dropped.add("memory")
    if role.spec.autonomy is not None:
        dropped.add("autonomy")
    if role.spec.reasoning is not None:
        dropped.add("reasoning")
    if role.spec.observability is not None:
        dropped.add("observability")
    if role.spec.auto_skills.enabled is False or role.spec.tool_search.enabled:
        dropped.add("auto_skills/tool_search")
    # Guardrails / security / resources exist as defaults on every role; only
    # flag them when non-default.  Post-init validators (e.g. Guardrails fills
    # ``max_request_limit``) make ``exclude_defaults`` unreliable, so compare
    # against a freshly-constructed default instance instead.
    from initrunner.agent.schema.guardrails import Guardrails
    from initrunner.agent.schema.security import ResourceConfig, SecurityPolicy

    if role.spec.guardrails.model_dump() != Guardrails().model_dump():
        dropped.add("guardrails")
    if role.spec.security.model_dump() != SecurityPolicy().model_dump():
        dropped.add("security")
    if role.spec.resources.model_dump() != ResourceConfig().model_dump():
        dropped.add("resources")

    return spec, dropped
