"""Pydantic models for flow YAML definitions."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from initrunner.agent.schema.ingestion import EmbeddingConfig
from initrunner.agent.schema.triggers import TriggerConfig
from initrunner.stores.base import StoreBackend


class EnsembleConfig(BaseModel):
    """Voting configuration for the ``ensemble`` delegate strategy.

    An ensemble sink broadcasts the same prompt to every target, then a
    reducer picks a single winning answer instead of concatenating them:

    - ``majority``: normalized vote on identical answers; ties break on the
      lowest topology index (deterministic).
    - ``weighted``: each target carries a YAML ``weights`` value; the answer
      from the highest-weight target wins.
    - ``judge``: an LLM judge (``eval/judge.py``) scores each answer against
      ``judge_criteria`` and the highest-scoring answer wins.
    """

    mode: Literal["majority", "weighted", "judge"] = "majority"
    judge_model: str = "openai:gpt-4o-mini"
    judge_criteria: list[str] = Field(default_factory=list)
    weights: dict[str, float] | None = None

    @model_validator(mode="after")
    def _validate_mode(self) -> EnsembleConfig:
        if self.mode == "weighted" and not self.weights:
            raise ValueError("ensemble mode 'weighted' requires a non-empty 'weights' map")
        if self.weights is not None:
            for name, weight in self.weights.items():
                if weight < 0:
                    raise ValueError(f"ensemble weight for '{name}' must be non-negative")
            if all(weight == 0 for weight in self.weights.values()):
                raise ValueError("ensemble weights cannot all be zero")
        return self


class LoopBackConfig(BaseModel):
    """A bounded loop-back edge for critic/refine supervisor patterns.

    When set on a delegate sink, the sink's downstream output is routed back to
    ``target`` (an upstream agent already on the path) so the pair can iterate.
    The loop is bounded two ways: it always stops after ``max_iterations``
    rounds, and it stops early when the ``until`` predicate matches the latest
    output. An immutable per-edge envelope carries the iteration counter, and
    the flow depth cap still applies, so a loop cannot run unbounded.

    ``until`` is a small predicate map keyed by the field to inspect on the
    output envelope. Only ``output`` (the latest agent text) is supported, and
    each condition is one of:

    - ``contains:<text>`` -- exit when the output contains ``<text>``
      (case-insensitive).
    - ``<op><number>`` where ``<op>`` is one of ``>``, ``>=``, ``<``, ``<=``,
      ``==`` -- exit when the first number parsed from the output satisfies the
      comparison (e.g. ``">0.8"`` for a self-reported confidence score).
    """

    type: Literal["loop-back"] = "loop-back"
    target: str
    max_iterations: int = Field(default=3, ge=1, le=20)
    until: dict[str, str] | None = None

    @model_validator(mode="after")
    def _validate_until(self) -> LoopBackConfig:
        if self.until is not None:
            for field_name, condition in self.until.items():
                if field_name != "output":
                    raise ValueError(
                        f"loop_back until only supports the 'output' field, got '{field_name}'"
                    )
                _parse_until_condition(condition)
        return self


def _parse_until_condition(
    condition: str,
) -> tuple[Literal["contains"], str] | tuple[Literal["compare"], str, float]:
    """Parse one ``until`` condition string into a structured form.

    Returns either ``("contains", text)`` or ``("compare", op, number)``.
    Raises ``ValueError`` on an unparseable condition.
    """
    stripped = condition.strip()
    if stripped.lower().startswith("contains:"):
        needle = stripped[len("contains:") :].strip()
        if not needle:
            raise ValueError("loop_back until 'contains:' needs a non-empty value")
        return ("contains", needle)
    for op in (">=", "<=", "==", ">", "<"):
        if stripped.startswith(op):
            value = stripped[len(op) :].strip()
            try:
                return ("compare", op, float(value))
            except ValueError:
                raise ValueError(
                    f"loop_back until comparison '{condition}' has a non-numeric value"
                ) from None
    raise ValueError(
        f"loop_back until condition '{condition}' must be 'contains:<text>' or '<op><number>'"
    )


class DelegateSinkConfig(BaseModel):
    type: Literal["delegate"] = "delegate"
    target: str | list[str]
    strategy: Literal["all", "keyword", "sense", "ensemble"] = "all"
    ensemble: EnsembleConfig | None = None
    loop_back: LoopBackConfig | None = None
    keep_existing_sinks: bool = False
    queue_size: int = 100
    timeout_seconds: int = 60
    circuit_breaker_threshold: int | None = None  # consecutive failures to trip; None = disabled
    circuit_breaker_reset_seconds: int = 60  # seconds before half-open probe

    @model_validator(mode="after")
    def _validate_ensemble(self) -> DelegateSinkConfig:
        if self.strategy == "ensemble":
            if self.ensemble is None:
                raise ValueError("strategy 'ensemble' requires an 'ensemble' config block")
            targets = self.target if isinstance(self.target, list) else [self.target]
            if len(targets) < 2:
                raise ValueError("strategy 'ensemble' requires at least two targets to vote on")
            if self.ensemble.weights is not None:
                unknown = set(self.ensemble.weights) - set(targets)
                if unknown:
                    raise ValueError(
                        f"ensemble weights reference unknown targets: {sorted(unknown)}"
                    )
        elif self.ensemble is not None:
            raise ValueError("'ensemble' config is only valid with strategy 'ensemble'")
        return self

    def summary(self) -> str:
        targets = self.target if isinstance(self.target, list) else [self.target]
        strategy_suffix = f" [{self.strategy}]" if self.strategy != "all" else ""
        if self.strategy == "ensemble" and self.ensemble is not None:
            strategy_suffix = f" [ensemble:{self.ensemble.mode}]"
        loop_suffix = ""
        if self.loop_back is not None:
            loop_suffix = f" (loop-back: {self.loop_back.target} x{self.loop_back.max_iterations})"
        return f"delegate: {', '.join(targets)}{strategy_suffix}{loop_suffix}"


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


class DurabilityConfig(BaseModel):
    """Audit-backed checkpoint/resume journal for a flow.

    When ``enabled`` is True with ``backend: journal``, each completed
    sub-agent delegation is recorded as a signed row in the append-only
    audit store, keyed by ``flow_run_id``. A crashed or interrupted flow
    can then be resumed with ``initrunner flow run --resume <flow_run_id>``:
    services that already produced a successful checkpoint are replayed from
    the journal instead of being re-run.

    ``backend`` only accepts working values. ``none`` (the default) means no
    journaling, so single-shot and REPL runs are unaffected. ``journal`` is
    the self-contained, audit-native durable ledger.
    """

    enabled: bool = False
    backend: Literal["none", "journal"] = "none"
    retry_policy: Literal["exponential", "linear", "none"] = "exponential"
    max_retries: int = 3
    retry_delay_seconds: int = 1

    @model_validator(mode="after")
    def _validate_backend(self) -> DurabilityConfig:
        if self.enabled and self.backend == "none":
            # Enabling durability implies the audit-backed journal.
            object.__setattr__(self, "backend", "journal")
        return self

    @property
    def active(self) -> bool:
        """True when checkpoints should be written and consulted."""
        return self.enabled and self.backend == "journal"


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
    durability: DurabilityConfig = DurabilityConfig()

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
                if agent.sink.loop_back is not None:
                    lb_target = agent.sink.loop_back.target
                    if lb_target not in agent_names:
                        raise ValueError(
                            f"Agent '{name}' loops back to unknown agent '{lb_target}'"
                        )
                    # Looping back to a forward delegate target is not a loop,
                    # it just re-runs that agent. Looping back to the source
                    # (the canonical writer -> critic -> writer refine loop) or
                    # to any other upstream agent is allowed.
                    if lb_target in targets:
                        raise ValueError(
                            f"Agent '{name}' cannot loop back to its delegate target '{lb_target}'"
                        )

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
        #
        # A loop-back edge ``source -> loop_back.target`` is an explicitly
        # marked back-edge. It is included in the topology but exempted from
        # cycle detection via ``allow_edges`` so the refine loop is permitted
        # while every other cycle is still rejected.
        delegate_forward: dict[str, list[str]] = {}
        loop_back_allow: dict[str, set[str]] = {}
        for name, agent in self.agents.items():
            if agent.sink is not None:
                targets = (
                    agent.sink.target
                    if isinstance(agent.sink.target, list)
                    else [agent.sink.target]
                )
                delegate_forward[name] = list(targets)
                if agent.sink.loop_back is not None:
                    lb_target = agent.sink.loop_back.target
                    delegate_forward[name].append(lb_target)
                    # Inverted edge is "lb_target depends on name".
                    loop_back_allow.setdefault(lb_target, set()).add(name)
            else:
                delegate_forward[name] = []

        inverted: dict[str, list[str]] = {n: [] for n in agent_names}
        for source, targets in delegate_forward.items():
            for target in targets:
                inverted[target].append(source)

        detect_cycle(agent_names, inverted, "delegate", allow_edges=loop_back_allow)

        return self


class FlowMetadata(BaseModel):
    name: str
    description: str = ""


class FlowDefinition(BaseModel):
    apiVersion: str
    kind: Literal["Flow"]
    metadata: FlowMetadata
    spec: FlowSpec
