"""Pydantic models for compose YAML definitions."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from initrunner.agent.schema.triggers import TriggerConfig
from initrunner.stores.base import StoreBackend


class DelegateSinkConfig(BaseModel):
    type: Literal["delegate"] = "delegate"
    target: str | list[str]
    keep_existing_sinks: bool = False
    queue_size: int = 100
    timeout_seconds: int = 60
    circuit_breaker_threshold: int | None = None  # consecutive failures to trip; None = disabled
    circuit_breaker_reset_seconds: int = 60  # seconds before half-open probe

    def summary(self) -> str:
        targets = self.target if isinstance(self.target, list) else [self.target]
        return f"delegate: {', '.join(targets)}"


class HealthCheckConfig(BaseModel):
    interval_seconds: int = 30
    timeout_seconds: int = 10
    retries: int = 3


class RestartPolicy(BaseModel):
    condition: Literal["none", "on-failure", "always"] = "none"
    max_retries: int = 3
    delay_seconds: int = 5


class SharedMemoryConfig(BaseModel):
    enabled: bool = False
    store_path: str | None = None
    store_backend: StoreBackend = StoreBackend.SQLITE_VEC
    max_memories: int = 1000


class ComposeServiceConfig(BaseModel):
    role: str
    trigger: TriggerConfig | None = None
    sink: DelegateSinkConfig | None = None
    depends_on: list[str] = []
    health_check: HealthCheckConfig = HealthCheckConfig()
    restart: RestartPolicy = RestartPolicy()
    environment: dict[str, str] = {}


class ComposeSpec(BaseModel):
    services: dict[str, ComposeServiceConfig] = Field(min_length=1)
    shared_memory: SharedMemoryConfig = SharedMemoryConfig()

    @model_validator(mode="after")
    def _validate_graph(self) -> ComposeSpec:
        service_names = set(self.services.keys())

        # Validate depends_on references
        for name, svc in self.services.items():
            for dep in svc.depends_on:
                if dep not in service_names:
                    raise ValueError(f"Service '{name}' depends on unknown service '{dep}'")
                if dep == name:
                    raise ValueError(f"Service '{name}' cannot depend on itself")

        # Validate delegate sink targets exist
        for name, svc in self.services.items():
            if svc.sink is not None:
                targets = (
                    svc.sink.target if isinstance(svc.sink.target, list) else [svc.sink.target]
                )
                for target in targets:
                    if target not in service_names:
                        raise ValueError(
                            f"Service '{name}' delegates to unknown service '{target}'"
                        )
                    if target == name:
                        raise ValueError(f"Service '{name}' cannot delegate to itself")

        # Cycle detection on depends_on graph (Kahn's algorithm)
        from initrunner._graph import detect_cycle

        detect_cycle(
            service_names,
            {name: svc.depends_on for name, svc in self.services.items()},
            "dependency",
        )

        # Cycle detection on delegate graph
        # Flip edges: delegate edges are "A points to B", but detect_cycle
        # expects "A depends on B". Invert so B depends on A.
        delegate_forward: dict[str, list[str]] = {}
        for name, svc in self.services.items():
            if svc.sink is not None:
                targets = (
                    svc.sink.target if isinstance(svc.sink.target, list) else [svc.sink.target]
                )
                delegate_forward[name] = list(targets)
            else:
                delegate_forward[name] = []

        inverted: dict[str, list[str]] = {n: [] for n in service_names}
        for source, targets in delegate_forward.items():
            for target in targets:
                inverted[target].append(source)

        detect_cycle(service_names, inverted, "delegate")

        return self


class ComposeMetadata(BaseModel):
    name: str
    description: str = ""


class ComposeDefinition(BaseModel):
    apiVersion: str
    kind: Literal["Compose"]
    metadata: ComposeMetadata
    spec: ComposeSpec
