"""Flat public agent document (spec_version 3).

Loaders adapt this onto today's Role / Team / Flow runner types.
"""

from __future__ import annotations

import re
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from initrunner.agent.schema.autonomy import AutonomyConfig
from initrunner.agent.schema.base import BundleConfig, PartialModelConfig
from initrunner.agent.schema.document import FLAT_SCHEMA_VERSION
from initrunner.agent.schema.execution import ExecutionConfig
from initrunner.agent.schema.guardrails import Guardrails
from initrunner.agent.schema.ingestion import IngestConfig
from initrunner.agent.schema.memory import MemoryConfig
from initrunner.agent.schema.observability import ObservabilityConfig
from initrunner.agent.schema.output import OutputConfig
from initrunner.agent.schema.reasoning import ReasoningConfig
from initrunner.agent.schema.role import (
    AutoSkillsConfig,
    DaemonConfig,
    ToolSearchConfig,
    parse_tool_list,
)
from initrunner.agent.schema.security import ResourceConfig, SecurityPolicy
from initrunner.agent.schema.sinks import SinkConfig
from initrunner.agent.schema.tools import ToolConfig
from initrunner.agent.schema.triggers import TriggerConfig
from initrunner.flow.schema import (
    DurabilityConfig,
    EnsembleConfig,
    LoopBackConfig,
    SharedMemoryConfig,
)
from initrunner.team.schema import DebateConfig, TeamDocumentsConfig, TeamEnsembleConfig

_NAME_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$")
_CHILD_NAME_RE = _NAME_RE
RunPreset = Literal["sequential", "parallel", "debate", "ensemble"]

# Fields a group of independent agents may set. Everything else configures how
# an agent behaves, which belongs to the member's own role file.
_GROUP_FIELDS = frozenset(
    {
        "name",
        "description",
        "tags",
        "author",
        "team",
        "version",
        "dependencies",
        "bundle",
        "spec_version",
        "agents",
        "shared_memory",
        "shared_documents",
        "observability",
        "security",
    }
)


class ThenConfig(BaseModel):
    """Graph edge. Mechanical rename of Flow ``DelegateSinkConfig`` (``target`` → ``to``)."""

    model_config = ConfigDict(extra="forbid")

    to: str | list[str]
    strategy: Literal["all", "keyword", "sense", "ensemble"] = "all"
    ensemble: EnsembleConfig | None = None
    loop_back: LoopBackConfig | None = None
    keep_existing_sinks: bool = False
    queue_size: int = 100
    timeout_seconds: int = 60
    circuit_breaker_threshold: int | None = None
    circuit_breaker_reset_seconds: int = 60

    @model_validator(mode="after")
    def _validate_ensemble(self) -> ThenConfig:
        if self.strategy == "ensemble":
            if self.ensemble is None:
                raise ValueError("strategy 'ensemble' requires an 'ensemble' config block")
            targets = self.to if isinstance(self.to, list) else [self.to]
            if len(targets) < 2:
                raise ValueError("strategy 'ensemble' requires at least two targets")
            if self.ensemble.weights is not None:
                unknown = set(self.ensemble.weights) - set(targets)
                if unknown:
                    raise ValueError(
                        f"ensemble weights reference unknown targets: {sorted(unknown)}"
                    )
        elif self.ensemble is not None:
            raise ValueError("'ensemble' config is only valid with strategy 'ensemble'")
        return self


class AgentGuardrails(Guardrails):
    """Solo guardrails plus optional composed budgets."""

    model_config = ConfigDict(extra="forbid")

    team_token_budget: Annotated[int, Field(gt=0)] | None = None
    team_timeout_seconds: Annotated[int, Field(gt=0)] | None = None


class AgentChild(BaseModel):
    """One composed child: inline prompt, file ref, or both (use + overrides)."""

    model_config = ConfigDict(extra="forbid")

    prompt: str | None = None
    use: str | None = None
    model: PartialModelConfig | None = None
    tools: list[ToolConfig] = []
    tools_mode: Literal["extend", "replace"] = "extend"
    environment: dict[str, str] = {}
    triggers: list[TriggerConfig] = []
    then: ThenConfig | None = None
    after: list[str] = []
    guardrails: AgentGuardrails | None = None

    @field_validator("model", mode="before")
    @classmethod
    def _coerce_model(cls, v: Any) -> Any:
        return coerce_model_shorthand(v)

    @field_validator("tools", mode="before")
    @classmethod
    def _parse_tools(cls, v: Any) -> list:
        return parse_v3_tool_list(v)

    @model_validator(mode="after")
    def _prompt_or_use(self) -> AgentChild:
        if not self.prompt and not self.use:
            raise ValueError("child needs 'prompt' or 'use'")
        return self


class AgentDocument(BaseModel):
    """Flat agent.yaml. ``extra='forbid'`` so unknown keys cannot vanish."""

    model_config = ConfigDict(extra="forbid")

    name: Annotated[str, Field(pattern=_NAME_RE.pattern)]
    description: str = ""
    tags: list[str] = []
    author: str = ""
    team: str = ""
    version: str = ""
    dependencies: list[str] = []
    bundle: BundleConfig | None = None
    spec_version: int | None = None

    prompt: str | None = None
    model: PartialModelConfig | None = None
    output: OutputConfig = Field(default_factory=OutputConfig)
    tools: list[ToolConfig] = []
    skills: list[str] = []
    capabilities: list = []
    deps_schema: dict[str, Any] | None = None
    triggers: list[TriggerConfig] = []
    sinks: list[SinkConfig] = []
    ingest: IngestConfig | None = None
    memory: MemoryConfig | None = None
    autonomy: AutonomyConfig | None = None
    reasoning: ReasoningConfig | None = None
    guardrails: AgentGuardrails = Field(default_factory=AgentGuardrails)
    execution: ExecutionConfig = Field(default_factory=ExecutionConfig)
    resources: ResourceConfig = Field(default_factory=ResourceConfig)
    security: SecurityPolicy = Field(default_factory=SecurityPolicy)
    observability: ObservabilityConfig | None = None
    auto_skills: AutoSkillsConfig = Field(default_factory=AutoSkillsConfig)
    tool_search: ToolSearchConfig = Field(default_factory=ToolSearchConfig)
    daemon: DaemonConfig = Field(default_factory=DaemonConfig)

    agents: dict[str, AgentChild] | None = None
    run: RunPreset | None = None
    debate: DebateConfig = Field(default_factory=DebateConfig)
    ensemble: TeamEnsembleConfig = Field(default_factory=TeamEnsembleConfig)
    handoff_max_chars: Annotated[int, Field(gt=0)] = 4000
    shared_memory: SharedMemoryConfig = Field(default_factory=SharedMemoryConfig)
    shared_documents: TeamDocumentsConfig = Field(default_factory=TeamDocumentsConfig)
    durability: DurabilityConfig | None = None

    @field_validator("spec_version")
    @classmethod
    def _spec_version_is_flat(cls, v: int | None) -> int | None:
        if v is None or v == FLAT_SCHEMA_VERSION:
            return v
        raise ValueError(
            f"flat documents use spec_version {FLAT_SCHEMA_VERSION} (or omit it), not {v}"
        )

    @field_validator("model", mode="before")
    @classmethod
    def _coerce_model(cls, v: Any) -> Any:
        return coerce_model_shorthand(v)

    @field_validator("tools", mode="before")
    @classmethod
    def _parse_tools(cls, v: Any) -> list:
        return parse_v3_tool_list(v)

    @field_validator("agents", mode="before")
    @classmethod
    def _normalize_agents(cls, v: Any) -> Any:
        if not isinstance(v, dict):
            return v
        out: dict[str, Any] = {}
        for name, value in v.items():
            if isinstance(value, str):
                out[name] = {"prompt": value}
            else:
                out[name] = value
        return out

    @field_validator("capabilities", mode="before")
    @classmethod
    def _parse_capabilities(cls, v: Any) -> list:
        if not isinstance(v, list):
            return v
        from pydantic_ai._spec import NamedSpec  # type: ignore[import-not-found]

        return [NamedSpec.model_validate(item) for item in v]

    def _grouped_agent_rules(self) -> None:
        """Reject group-level fields that belong to a member's own role file.

        A group is a deployment manifest: it says which agents run together and
        what they share, not how any of them behaves. Anything that configures
        behaviour is silently misleading here, so it is an error instead.
        """
        extra = sorted(self.model_fields_set - _GROUP_FIELDS)
        if extra:
            raise ValueError(
                f"{extra} cannot be set on a group of agents. Group files support "
                "metadata, shared_memory, shared_documents, observability and "
                "security.server / security.rate_limit. Move these into the member's "
                "role file, or add 'run:' to run the members as a team"
            )
        listener_only = self.security.model_fields_set - {"server", "rate_limit"}
        if listener_only:
            raise ValueError(
                f"security.{sorted(listener_only)} cannot be set on a group of agents. "
                "Group security covers only the shared listener ('server', "
                "'rate_limit'); tool, sandbox and content policy stay in each "
                "member's role file"
            )

    @model_validator(mode="after")
    def _composition_rules(self) -> AgentDocument:
        composed = bool(self.agents)
        if composed and self.prompt:
            raise ValueError(
                "top-level 'prompt' is not allowed when 'agents' is set; "
                "put instructions on each child (a coordinator is just another child)"
            )
        if not composed and not self.prompt:
            raise ValueError("solo agents require 'prompt'")

        if not composed:
            if self.run is not None:
                raise ValueError("'run' is only valid when 'agents' is set")
            if self.guardrails.team_token_budget is not None:
                raise ValueError("team_token_budget is only valid when 'agents' is set")
            if self.guardrails.team_timeout_seconds is not None:
                raise ValueError("team_timeout_seconds is only valid when 'agents' is set")
            if self.durability is not None:
                raise ValueError("'durability' is only valid when 'agents' is set")
            if self.shared_memory.enabled:
                raise ValueError("shared_memory is only valid when 'agents' is set")
            if self.shared_documents.enabled:
                raise ValueError("shared_documents is only valid when 'agents' is set")
            return self

        assert self.agents is not None
        for name in self.agents:
            if not _CHILD_NAME_RE.match(name):
                raise ValueError(
                    f"Invalid agent name '{name}': must match {_CHILD_NAME_RE.pattern}"
                )

        has_then = any(child.then is not None for child in self.agents.values())
        has_after = any(child.after for child in self.agents.values())
        # Captured before the injection below, which would mark 'run' as set.
        explicit_run = self.run is not None
        if (has_then or has_after) and explicit_run:
            raise ValueError("pick 'run' (preset) or 'then'/'after' (graph), not both")
        if not has_then and not has_after:
            if explicit_run and len(self.agents) == 1:
                raise ValueError(
                    "'run' needs at least two agents; drop 'run', or add another agent"
                )
            if not explicit_run:
                bare = {
                    name for name, child in self.agents.items() if child.model_fields_set == {"use"}
                }
                if len(bare) == len(self.agents):
                    # Grouped agents: every member is a bare reference to another
                    # agent file, so there is nothing to orchestrate and no
                    # strategy to inject.
                    self._grouped_agent_rules()
                    return self
                if bare:
                    raise ValueError(
                        f"agents {sorted(bare)} are bare 'use:' references while "
                        f"{sorted(set(self.agents) - bare)} are defined inline or add "
                        "overrides, so this is neither a team nor a group. Add "
                        "'run: sequential' (or parallel, debate, ensemble) to run them "
                        "as a team, or move the inline definitions and overrides into "
                        "role files to deploy them as independent agents"
                    )
                self.run = "sequential"

        if not has_then and not has_after and len(self.agents) > 1:
            for name, child in self.agents.items():
                if "triggers" in child.model_fields_set:
                    raise ValueError(
                        f"Per-child triggers are not supported by preset teams (agent '{name}')"
                    )
                if child.guardrails is not None:
                    raise ValueError(
                        f"Per-child guardrails are not supported by preset teams (agent '{name}')"
                    )

        if self.durability is not None and not has_then:
            # durability is a Flow journal; presets do not checkpoint
            raise ValueError("'durability' is only valid on a graph (children with 'then')")

        concurrent = has_then or has_after or (self.run in ("parallel", "debate", "ensemble"))
        if concurrent:
            for name, child in self.agents.items():
                if child.environment:
                    raise ValueError(
                        f"Per-child environment is only valid with run: sequential (agent '{name}')"
                    )

        names = set(self.agents)
        for name, child in self.agents.items():
            for dep in child.after:
                if dep not in names:
                    raise ValueError(f"Agent '{name}' after references unknown '{dep}'")
                if dep == name:
                    raise ValueError(f"Agent '{name}' cannot after itself")
            if child.then is None:
                continue
            targets = child.then.to if isinstance(child.then.to, list) else [child.then.to]
            for target in targets:
                if target not in names:
                    raise ValueError(f"Agent '{name}' then.to references unknown '{target}'")
                if target == name:
                    raise ValueError(f"Agent '{name}' cannot then.to itself")
            if child.then.loop_back is not None:
                lb = child.then.loop_back.target
                if lb not in names:
                    raise ValueError(f"Agent '{name}' loops back to unknown '{lb}'")
                if lb in targets:
                    raise ValueError(f"Agent '{name}' cannot loop back to its then target '{lb}'")

        return self


def coerce_model_shorthand(v: Any) -> Any:
    """``openai:gpt-5-mini`` → ``{provider, name}``. Leave mappings alone."""
    if not isinstance(v, str):
        return v
    if ":" in v:
        provider, name = v.split(":", 1)
        return {"provider": provider, "name": name}
    return {"name": v}


def expand_tool_shorthand(v: Any) -> Any:
    """Normalize v3 tool list items to ``{type: ..., ...}`` dicts."""
    if not isinstance(v, list):
        return v
    expanded: list[Any] = []
    for item in v:
        if isinstance(item, str):
            expanded.append({"type": item})
            continue
        if isinstance(item, dict):
            if "type" in item:
                expanded.append(item)
                continue
            if len(item) != 1:
                raise ValueError(
                    "tool mapping must be a '{type: ...}' object or a single '{name: config}' pair"
                )
            type_name, config = next(iter(item.items()))
            if not isinstance(type_name, str):
                raise ValueError("tool type name must be a string")
            if config is None:
                config = {}
            if not isinstance(config, dict):
                raise ValueError(f"config for tool '{type_name}' must be a mapping")
            expanded.append({"type": type_name, **config})
            continue
        expanded.append(item)
    return expanded


def parse_v3_tool_list(v: Any) -> list:
    """Expand shorthand, parse builtin tools, reject unknown keys on builtins."""
    expanded = expand_tool_shorthand(v)
    parsed = parse_tool_list(expanded)
    if not isinstance(expanded, list):
        return parsed
    from initrunner.agent.tools._registry import get_tool_types

    builtin_types = get_tool_types()
    for raw, model in zip(expanded, parsed, strict=False):
        if not isinstance(raw, dict):
            continue
        tool_type = raw.get("type")
        if tool_type not in builtin_types:
            continue
        allowed = set(type(model).model_fields)
        extra = set(raw) - allowed
        if extra:
            raise ValueError(f"Unknown keys for tool '{tool_type}': {sorted(extra)}")
    return parsed
