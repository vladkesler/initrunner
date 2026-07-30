"""Always-on service catalog schema (kind: Service)."""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from initrunner.agent.schema.base import ApiVersion, Metadata

# CLI slug / instance directory name. Single segment only (no slashes).
SERVICE_NAME_RE = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$")
ServiceName = Annotated[str, Field(pattern=SERVICE_NAME_RE.pattern)]


class ServiceKind(StrEnum):
    SERVICE = "Service"


class ServiceParamType(StrEnum):
    STRING = "string"
    ENUM = "enum"
    INT = "int"
    BOOL = "bool"


class ServiceParam(BaseModel):
    """Start-time parameter declared by a service."""

    type: ServiceParamType = ServiceParamType.STRING
    required: bool = False
    default: Any = None
    description: str = ""
    values: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _enum_requires_values(self) -> ServiceParam:
        if self.type == ServiceParamType.ENUM and not self.values:
            raise ValueError("enum params require a non-empty values list")
        return self


class ServiceEntry(BaseModel):
    """What the service runs after start (Agent role only in v1)."""

    kind: Literal["Agent"] = "Agent"
    path: str = "role.yaml"


class ServiceRequires(BaseModel):
    """Hard requirements checked before start succeeds."""

    env: list[str] = Field(default_factory=list)
    extras: list[str] = Field(default_factory=list)


class ServiceDefaults(BaseModel):
    """Defaults applied when materializing the instance role."""

    sinks: list[dict[str, Any]] = Field(default_factory=list)
    guardrails: dict[str, Any] = Field(default_factory=dict)
    timezone: str = "UTC"
    autonomy: bool = False


class ServiceSpec(BaseModel):
    entry: ServiceEntry = ServiceEntry()
    params: dict[str, ServiceParam] = Field(default_factory=dict)
    primary_param: str | None = None
    every: str = "daily"
    defaults: ServiceDefaults = ServiceDefaults()
    requires: ServiceRequires = ServiceRequires()
    schedule_prompt: str = "Run the scheduled service task."

    @model_validator(mode="after")
    def _primary_param_valid(self) -> ServiceSpec:
        if self.primary_param is None:
            return self
        if self.primary_param not in self.params:
            raise ValueError(f"primary_param '{self.primary_param}' is not declared in params")
        if not self.params[self.primary_param].required:
            raise ValueError(f"primary_param '{self.primary_param}' must be a required parameter")
        return self


class ServiceDefinition(BaseModel):
    """Root document for service.yaml."""

    apiVersion: ApiVersion = ApiVersion.V1
    kind: ServiceKind = ServiceKind.SERVICE
    metadata: Metadata
    spec: ServiceSpec

    @field_validator("kind", mode="before")
    @classmethod
    def _coerce_kind(cls, v: object) -> object:
        if isinstance(v, str) and v == "Service":
            return ServiceKind.SERVICE
        return v

    @field_validator("metadata", mode="after")
    @classmethod
    def _slug_name(cls, meta: Metadata) -> Metadata:
        if not SERVICE_NAME_RE.fullmatch(meta.name):
            raise ValueError(f"Invalid service name '{meta.name}'")
        return meta


class ServiceStatus(StrEnum):
    RUNNING = "running"
    STOPPED = "stopped"


class ProcessIdentity(BaseModel):
    """Linux process identity evidence for a supervised daemon."""

    pid: int
    boot_id: str
    proc_start_ticks: int
    role_path: str
    started_at: str | None = None  # display only


class ServiceState(BaseModel):
    """Runtime state for one started service instance (state.json)."""

    slug: ServiceName
    service_version: str = ""
    status: ServiceStatus = ServiceStatus.STOPPED
    params: dict[str, Any] = Field(default_factory=dict)
    sinks: list[dict[str, Any]] = Field(default_factory=list)
    every: str = "daily"
    resolved_cron: str = ""
    timezone: str = "UTC"
    started_at: str | None = None  # first start wall clock (display)
    stopped_at: str | None = None
    generation: int = 0
    role_file: str = ""  # e.g. role.1.yaml
    role_digest: str = ""
    state_version: int = 1
    catalog_path: str = ""
    process: ProcessIdentity | None = None
    last_error: str | None = None
    output_paths: list[str] = Field(default_factory=list)
