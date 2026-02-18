"""Agent spec and role definition (aggregation root)."""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from initrunner.agent.schema.autonomy import AutonomyConfig
from initrunner.agent.schema.base import ApiVersion, Kind, Metadata, ModelConfig
from initrunner.agent.schema.guardrails import Guardrails
from initrunner.agent.schema.ingestion import IngestConfig
from initrunner.agent.schema.memory import MemoryConfig
from initrunner.agent.schema.observability import ObservabilityConfig
from initrunner.agent.schema.output import OutputConfig
from initrunner.agent.schema.security import ResourceConfig, SecurityPolicy
from initrunner.agent.schema.sinks import SinkConfig
from initrunner.agent.schema.tools import PluginToolConfig, ToolConfig
from initrunner.agent.schema.triggers import TriggerConfig


def parse_tool_list(v: Any) -> list:
    """Parse a list of tool config dicts into typed ToolConfig instances.

    Shared by AgentSpec and SkillFrontmatter validators.
    """
    if not isinstance(v, list):
        return v

    # Lazy import inside function body to avoid circular import with _registry
    from initrunner.agent.tools._registry import get_tool_types

    builtin_types = get_tool_types()
    result = []
    for item in v:
        if not isinstance(item, dict):
            result.append(item)
            continue
        tool_type = item.get("type")
        if tool_type in builtin_types:
            try:
                result.append(builtin_types[tool_type].model_validate(item))
            except ValidationError as exc:
                raise ValueError(f"Invalid config for tool '{tool_type}': {exc}") from exc
        else:
            config = {k: val for k, val in item.items() if k != "type"}
            result.append(PluginToolConfig(type=tool_type, config=config))
    return result


class AgentSpec(BaseModel):
    role: str
    model: ModelConfig
    output: OutputConfig = OutputConfig()
    tools: list[ToolConfig] = []
    skills: list[str] = []
    triggers: list[TriggerConfig] = []
    sinks: list[SinkConfig] = []
    ingest: IngestConfig | None = None
    memory: MemoryConfig | None = None
    autonomy: AutonomyConfig | None = None
    guardrails: Guardrails = Guardrails()
    resources: ResourceConfig = ResourceConfig()
    security: SecurityPolicy = SecurityPolicy()
    observability: ObservabilityConfig | None = None

    @field_validator("tools", mode="before")
    @classmethod
    def _parse_tools(cls, v: Any) -> list:
        return parse_tool_list(v)


class RequiresConfig(BaseModel):
    """External dependencies a skill needs (validated at load time)."""

    env: list[str] = []
    bins: list[str] = []


class SkillFrontmatter(BaseModel):
    """Parsed from YAML frontmatter in SKILL.md files.

    Standard agentskills.io fields: name, description, license, compatibility,
    metadata, allowed_tools. InitRunner extensions: tools, requires.
    """

    # agentskills.io standard fields
    name: Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9-]*[a-z0-9]$")]
    description: str
    license: str = ""
    compatibility: str = ""
    metadata: dict[str, str] = {}
    allowed_tools: str = ""

    # InitRunner extensions
    tools: list[ToolConfig] = []
    requires: RequiresConfig = RequiresConfig()

    model_config = ConfigDict(extra="ignore")

    @field_validator("tools", mode="before")
    @classmethod
    def _parse_tools(cls, v: Any) -> list:
        return parse_tool_list(v)


class SkillDefinition(BaseModel):
    """Internal representation of a loaded skill (frontmatter + body)."""

    frontmatter: SkillFrontmatter
    prompt: str


class RoleDefinition(BaseModel):
    apiVersion: ApiVersion
    kind: Kind
    metadata: Metadata
    spec: AgentSpec
