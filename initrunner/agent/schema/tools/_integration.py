"""Integration tool configurations: MCP, API, custom, delegate, spawn, plugin."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from initrunner.agent.schema.tools._base import ToolConfigBase


class McpToolConfig(ToolConfigBase):
    type: Literal["mcp"] = "mcp"
    transport: Literal["stdio", "sse", "streamable-http"] = "stdio"
    command: str | None = None
    args: list[str] = []
    url: str | None = None
    tool_filter: list[str] = []
    tool_exclude: list[str] = []
    headers: dict[str, str] = {}
    env: dict[str, str] = {}
    cwd: str | None = None
    tool_prefix: str | None = None
    max_retries: int = 1
    timeout_seconds: int | None = None
    defer: bool = False

    @model_validator(mode="after")
    def _validate_transport_fields(self) -> McpToolConfig:
        if self.transport == "stdio" and not self.command:
            raise ValueError("MCP stdio transport requires 'command'")
        if self.transport in ("sse", "streamable-http") and not self.url:
            raise ValueError(f"MCP {self.transport} transport requires 'url'")
        if self.tool_filter and self.tool_exclude:
            raise ValueError("'tool_filter' and 'tool_exclude' are mutually exclusive")
        return self

    def summary(self) -> str:
        if self.command:
            label = " ".join([self.command, *self.args])
        else:
            label = self.url or ""
        return f"mcp: {self.transport} {label}"


class ApiParameter(BaseModel):
    name: str  # must be valid Python identifier
    type: Literal["string", "integer", "number", "boolean"]  # JSON Schema types
    required: bool = False
    default: Any = None
    description: str = ""

    @field_validator("name")
    @classmethod
    def _valid_identifier(cls, v: str) -> str:
        if not v.isidentifier():
            raise ValueError(f"'{v}' is not a valid Python identifier")
        return v


class ApiEndpoint(BaseModel):
    name: str  # becomes the tool function name
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"] = "GET"
    path: str  # supports {param} placeholders
    description: str = ""
    parameters: list[ApiParameter] = []
    headers: dict[str, str] = {}
    body_template: dict[str, Any] | None = None
    query_params: dict[str, str] = {}
    response_extract: str | None = None  # "$.data.id" or None for full text
    timeout_seconds: int = 30


class ApiToolConfig(ToolConfigBase):
    type: Literal["api"] = "api"
    name: str
    description: str = ""
    base_url: str
    headers: dict[str, str] = {}
    auth: dict[str, str] = {}
    endpoints: list[ApiEndpoint]

    def summary(self) -> str:
        return f"api: {self.name} ({len(self.endpoints)} endpoints)"


class CustomToolConfig(ToolConfigBase):
    type: Literal["custom"] = "custom"
    module: str
    function: str | None = None  # None → auto-discover all public callables
    config: dict[str, Any] = {}  # injected into functions that accept tool_config param

    def summary(self) -> str:
        if self.function:
            return f"custom: {self.module}.{self.function}"
        return f"custom: {self.module} (toolset)"


class DelegateAgentRef(BaseModel):
    name: str
    role_file: str | None = None
    url: str | None = None
    description: str = ""
    headers_env: dict[str, str] = {}


class DelegateSharedMemory(BaseModel):
    """Shared memory config for delegate sub-agents."""

    store_path: str
    max_memories: int = 1000


class DelegateToolConfig(ToolConfigBase):
    type: Literal["delegate"] = "delegate"
    agents: list[DelegateAgentRef]
    mode: Literal["inline", "mcp", "a2a"] = "inline"
    max_depth: int = 3
    timeout_seconds: int = 120
    shared_memory: DelegateSharedMemory | None = None

    @model_validator(mode="after")
    def _validate_agents(self) -> DelegateToolConfig:
        for agent in self.agents:
            if self.mode == "inline" and not agent.role_file:
                raise ValueError(f"Inline mode requires 'role_file' on agent '{agent.name}'")
            if self.mode in ("mcp", "a2a") and not agent.url:
                raise ValueError(f"{self.mode.upper()} mode requires 'url' on agent '{agent.name}'")
        return self

    def summary(self) -> str:
        names = ", ".join(a.name for a in self.agents)
        return f"delegate ({self.mode}): {names}"


class SpawnAgentRef(BaseModel):
    name: str
    role_file: str | None = None
    url: str | None = None
    description: str = ""


class SpawnToolConfig(ToolConfigBase):
    type: Literal["spawn"] = "spawn"
    agents: list[SpawnAgentRef]
    max_concurrent: int = Field(default=4, ge=1, le=16)
    max_depth: int = 3
    timeout_seconds: int = 300
    shared_memory: DelegateSharedMemory | None = None

    @model_validator(mode="after")
    def _validate_agents(self) -> SpawnToolConfig:
        for agent in self.agents:
            if not agent.role_file and not agent.url:
                raise ValueError(f"Spawn agent '{agent.name}' requires 'role_file' or 'url'")
        return self

    def summary(self) -> str:
        names = ", ".join(a.name for a in self.agents[:3])
        return f"spawn: {names}"


class PluginToolConfig(ToolConfigBase):
    type: str
    config: dict[str, Any] = {}

    def summary(self) -> str:
        return f"plugin: {self.type}"
