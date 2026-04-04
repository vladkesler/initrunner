"""Pydantic models for flow YAML definitions."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from initrunner.agent.schema.ingestion import EmbeddingConfig
from initrunner.agent.schema.triggers import TriggerConfig
from initrunner.stores.base import StoreBackend


class DelegateSinkConfig(BaseModel):
    type: Literal["delegate"] = "delegate"
    target: str | list[str]
    strategy: Literal["all", "keyword", "sense"] = "all"
    keep_existing_sinks: bool = False
    queue_size: int = 100
    timeout_seconds: int = 60
    circuit_breaker_threshold: int | None = None  # consecutive failures to trip; None = disabled
    circuit_breaker_reset_seconds: int = 60  # seconds before half-open probe

    def summary(self) -> str:
        targets = self.target if isinstance(self.target, list) else [self.target]
        strategy_suffix = f" [{self.strategy}]" if self.strategy != "all" else ""
        return f"delegate: {', '.join(targets)}{strategy_suffix}"


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
    store_backend: StoreBackend = StoreBackend.LANCEDB
    max_memories: int = 1000


class SharedDocumentsConfig(BaseModel):
    enabled: bool = False
    store_path: str | None = None
    store_backend: StoreBackend = StoreBackend.LANCEDB
    embeddings: EmbeddingConfig = EmbeddingConfig()

    @model_validator(mode="after")
    def _validate_embeddings_when_enabled(self) -> SharedDocumentsConfig:
        if self.enabled:
            if not self.embeddings.provider:
                raise ValueError("shared_documents.embeddings.provider is required when enabled")
            if not self.embeddings.model:
                raise ValueError("shared_documents.embeddings.model is required when enabled")
        return self


class FlowAgentConfig(BaseModel):
    role: str
    trigger: TriggerConfig | None = None
    sink: DelegateSinkConfig | None = None
    needs: list[str] = []
    health_check: HealthCheckConfig = HealthCheckConfig()
    restart: RestartPolicy = RestartPolicy()
    environment: dict[str, str] = {}


class FlowSpec(BaseModel):
    agents: dict[str, FlowAgentConfig] = Field(min_length=1)
    shared_memory: SharedMemoryConfig = SharedMemoryConfig()
    shared_documents: SharedDocumentsConfig = SharedDocumentsConfig()

    @model_validator(mode="after")
    def _validate_graph(self) -> FlowSpec:
        agent_names = set(self.agents.keys())

        # Validate needs references
        for name, agent in self.agents.items():
            for dep in agent.needs:
                if dep not in agent_names:
                    raise ValueError(f"Agent '{name}' needs unknown agent '{dep}'")
                if dep == name:
                    raise ValueError(f"Agent '{name}' cannot need itself")

        # Validate delegate sink targets exist
        for name, agent in self.agents.items():
            if agent.sink is not None:
                targets = (
                    agent.sink.target
                    if isinstance(agent.sink.target, list)
                    else [agent.sink.target]
                )
                for target in targets:
                    if target not in agent_names:
                        raise ValueError(f"Agent '{name}' delegates to unknown agent '{target}'")
                    if target == name:
                        raise ValueError(f"Agent '{name}' cannot delegate to itself")

        # Cycle detection on needs graph (Kahn's algorithm)
        from initrunner._graph import detect_cycle

        detect_cycle(
            agent_names,
            {name: agent.needs for name, agent in self.agents.items()},
            "dependency",
        )

        # Cycle detection on delegate graph
        # Flip edges: delegate edges are "A points to B", but detect_cycle
        # expects "A depends on B". Invert so B depends on A.
        delegate_forward: dict[str, list[str]] = {}
        for name, agent in self.agents.items():
            if agent.sink is not None:
                targets = (
                    agent.sink.target
                    if isinstance(agent.sink.target, list)
                    else [agent.sink.target]
                )
                delegate_forward[name] = list(targets)
            else:
                delegate_forward[name] = []

        inverted: dict[str, list[str]] = {n: [] for n in agent_names}
        for source, targets in delegate_forward.items():
            for target in targets:
                inverted[target].append(source)

        detect_cycle(agent_names, inverted, "delegate")

        return self


class FlowMetadata(BaseModel):
    name: str
    description: str = ""


class FlowDefinition(BaseModel):
    apiVersion: str
    kind: Literal["Flow"]
    metadata: FlowMetadata
    spec: FlowSpec
