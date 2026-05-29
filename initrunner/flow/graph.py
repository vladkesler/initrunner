"""Graph-based flow execution using pydantic-graph beta.

Replaces the queue-based BFS execution with a pydantic-graph that
models the flow agent topology directly.  Fork/Join provides
native parallel execution for fan-out patterns.
"""

from __future__ import annotations

import asyncio
import json
import queue
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Any

import anyio
from pydantic_graph import GraphBuilder, StepContext
from pydantic_graph.id_types import ForkID, NodeID
from pydantic_graph.join import reduce_list_append

from initrunner._async import run_sync
from initrunner._log import get_logger
from initrunner.agent.executor import RunResult, execute_run_async
from initrunner.agent.tool_events import (
    ToolEvent,
    reset_tool_event_callback,
    set_tool_event_callback,
)

if TYPE_CHECKING:
    from pydantic_ai import Agent

    from initrunner.agent.schema.role import RoleDefinition
    from initrunner.audit.logger import AuditLogger
    from initrunner.flow.checkpoint import CheckpointJournal
    from initrunner.flow.schema import EnsembleConfig, FlowDefinition
    from initrunner.sinks.dispatcher import SinkDispatcher
    from initrunner.triggers.dispatcher import TriggerDispatcher

logger = get_logger("flow.graph")

_MAX_DELEGATION_DEPTH = 20


def _try_import_otel_context():
    """Import and return ``opentelemetry.context``, or ``None`` if unavailable."""
    try:
        from opentelemetry import context  # type: ignore[import-not-found]

        return context
    except ImportError:
        return None


# ---------------------------------------------------------------------------
# Envelope -- immutable per-edge data, never shared across fan-out branches
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DelegationEnvelope:
    """Immutable data flowing along each graph edge."""

    prompt: str
    trace: tuple[str, ...] = ()
    original_prompt: str = ""
    source_service: str | None = None
    message_history: list | None = None
    one_shot: bool = True
    topology_index: int = 0
    vote_trace: dict | None = None  # set by ensemble reducers; audited downstream
    loop_back_iteration: int = 0  # rounds completed on a loop-back edge so far


# ---------------------------------------------------------------------------
# Blackboard -- mutable shared state, threaded as the graph state for one run
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BlackboardEntry:
    """A single structured entry on the blackboard with provenance.

    Entries are immutable once posted; replacing a key requires claiming the
    old entry first. ``value`` is an opaque string (callers post JSON when they
    need structure), ``author`` is the agent that posted it, and ``timestamp``
    is an ISO-8601 UTC string.
    """

    key: str
    value: str
    author: str
    timestamp: str
    entry_id: str

    def as_dict(self) -> dict[str, str]:
        return {
            "key": self.key,
            "value": self.value,
            "author": self.author,
            "timestamp": self.timestamp,
            "entry_id": self.entry_id,
        }


@dataclass
class Blackboard:
    """Per-flow-run shared state passed as the pydantic-graph state.

    pydantic-graph runs steps sequentially within a branch and merges branches
    at a join, so the board is mutated by one step at a time; no locking is
    needed. Fan-in joins read structured entries from here instead of relying
    only on concatenated prompt text.
    """

    entries: dict[str, BlackboardEntry] = field(default_factory=dict)
    claimed: set[str] = field(default_factory=set)
    max_entries: int = 100

    def post(self, key: str, value: str, author: str) -> str:
        """Add an entry and return its generated id.

        Raises ``ValueError`` when the key already exists or the board is full.
        """
        if key in self.entries:
            raise ValueError(f"key '{key}' already exists; claim it first to replace")
        if len(self.entries) >= self.max_entries:
            raise ValueError(f"blackboard full ({self.max_entries} entries)")
        from initrunner._ids import generate_id

        entry = BlackboardEntry(
            key=key,
            value=value,
            author=author,
            timestamp=datetime.now(UTC).isoformat(),
            entry_id=generate_id(8),
        )
        self.entries[key] = entry
        return entry.entry_id

    def read(self, key: str) -> dict[str, str]:
        """Return the entry as a dict without removing it. Raises if missing."""
        entry = self.entries.get(key)
        if entry is None:
            raise ValueError(f"key '{key}' not found")
        return entry.as_dict()

    def claim(self, key: str) -> str:
        """Read an entry, remove it from the board, and return it as JSON.

        Raises ``ValueError`` when the key is absent (including a second claim).
        """
        payload = self.read(key)
        self.claimed.add(key)
        del self.entries[key]
        return json.dumps(payload)

    def summarize(self, value_preview_chars: int) -> str:
        """Render a bounded human-readable listing of the current entries."""
        if not self.entries:
            return "Blackboard is empty."
        lines = ["Blackboard entries:"]
        for key, entry in self.entries.items():
            value = entry.value
            if len(value) > value_preview_chars:
                value = value[:value_preview_chars] + " [truncated]"
            lines.append(f"  {key} (by {entry.author}): {value}")
        return "\n".join(lines)

    def snapshot(self) -> dict[str, Any]:
        """Serialize the unclaimed board for audit persistence."""
        return {
            "entries": {key: entry.as_dict() for key, entry in self.entries.items()},
            "claimed": sorted(self.claimed),
        }


# ---------------------------------------------------------------------------
# Graph dependencies
# ---------------------------------------------------------------------------


@dataclass
class FlowGraphDeps:
    """Injected into every graph step."""

    services: dict[str, AgentRef]
    flow_name: str
    audit_logger: AuditLogger | None
    on_service_start: Callable[[str], None] | None
    on_service_complete: Callable[[str, RunResult], None] | None
    entry_service: str
    flow_run_id: str = ""
    on_tool_event: Callable[[str, ToolEvent], None] | None = None
    checkpoint_journal: CheckpointJournal | None = None


@dataclass
class AgentRef:
    """Thin reference to a flow agent for graph steps."""

    name: str
    role: RoleDefinition
    agent: Agent
    sink_dispatcher: SinkDispatcher | None
    last_result: RunResult | None = None
    last_messages: list | None = None
    run_count: int = 0
    error_count: int = 0


# Backward-compatible alias
_AgentRef = AgentRef


# ---------------------------------------------------------------------------
# Topology containers
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _LoopBackEdge:
    """An explicitly-marked bounded loop-back edge (critic/refine pattern).

    ``source`` is the agent whose sink declares the loop. ``forward_target`` is
    the agent that ``source`` delegates to (the critic); its output feeds the
    loop decision. ``target`` is the agent the loop returns to (the writer).
    ``until_condition(envelope) -> bool`` returns True to exit the loop early;
    it is ``None`` when only ``max_iterations`` bounds the loop.
    """

    source: str
    forward_target: str
    target: str
    max_iterations: int
    until_condition: Callable[[DelegationEnvelope], bool] | None = None


@dataclass(frozen=True, slots=True)
class _TopologyInfo:
    """Computed delegation topology (pure data, no builder dependency)."""

    topology_index: dict[str, int]
    delegation_edges: dict[str, list[str]]
    reverse_edges: dict[str, list[str]]
    strategies: dict[str, str]
    entry_name: str
    reachable: set[str]
    ensemble_configs: dict[str, EnsembleConfig] = field(default_factory=dict)
    loop_back_edges: dict[str, _LoopBackEdge] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class _GraphNodes:
    """All nodes registered on the graph builder."""

    steps: dict[str, object]
    fan_in_targets: set[str]
    joins: dict[str, object]
    join_transforms: dict[str, object]
    terminal_services: set[str]
    terminal_joins: dict[str, object]
    terminal_join_transforms: dict[str, object]
    loop_back_deciders: dict[str, object] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Daemon ingress
# ---------------------------------------------------------------------------


@dataclass
class _RunRequest:
    entry: str
    prompt: str
    metadata: dict[str, str] = field(default_factory=dict)
    flow_run_id: str = ""
    resume: bool = False


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------


def _make_until_predicate(
    until: dict[str, str] | None,
) -> Callable[[DelegationEnvelope], bool] | None:
    """Compile a loop-back ``until`` config into an envelope predicate.

    Returns a callable ``(envelope) -> bool`` that is True when the loop should
    exit early, or ``None`` when only ``max_iterations`` bounds the loop. The
    predicate inspects the latest agent output (``envelope.prompt``). All
    conditions must hold for the loop to exit (logical AND).
    """
    if not until:
        return None

    from initrunner.flow.schema import _parse_until_condition

    parsed = [_parse_until_condition(condition) for condition in until.values()]

    def predicate(envelope: DelegationEnvelope) -> bool:
        text = envelope.prompt
        for cond in parsed:
            if cond[0] == "contains":
                if cond[1].lower() not in text.lower():
                    return False
            else:
                number = _first_number(text)
                if number is None or not _compare(number, cond[1], cond[2]):
                    return False
        return True

    return predicate


def _first_number(text: str) -> float | None:
    """Parse the first numeric token (int or float) from ``text``."""
    import re

    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if match is None:
        return None
    return float(match.group())


def _compare(value: float, op: str, threshold: float) -> bool:
    """Evaluate ``value op threshold`` for a supported comparison operator."""
    if op == ">":
        return value > threshold
    if op == ">=":
        return value >= threshold
    if op == "<":
        return value < threshold
    if op == "<=":
        return value <= threshold
    return value == threshold


def _compute_topology(
    flow: FlowDefinition,
    agent_refs: dict[str, AgentRef],
) -> _TopologyInfo:
    """Compute delegation topology: edges, strategies, entry point, reachable set."""
    topology_index: dict[str, int] = {name: i for i, name in enumerate(flow.spec.agents)}

    delegation_edges: dict[str, list[str]] = {}
    reverse_edges: dict[str, list[str]] = {}
    strategies: dict[str, str] = {}
    ensemble_configs: dict[str, EnsembleConfig] = {}
    loop_back_edges: dict[str, _LoopBackEdge] = {}

    for name, config in flow.spec.agents.items():
        if name not in agent_refs:
            continue
        if config.sink is None or not config.sink.target:
            delegation_edges[name] = []
            continue
        targets = (
            config.sink.target if isinstance(config.sink.target, list) else [config.sink.target]
        )
        reachable_targets = [t for t in targets if t in agent_refs]
        delegation_edges[name] = reachable_targets
        strategies[name] = config.sink.strategy
        if config.sink.strategy == "ensemble" and config.sink.ensemble is not None:
            ensemble_configs[name] = config.sink.ensemble
        for t in reachable_targets:
            reverse_edges.setdefault(t, []).append(name)
        lb = config.sink.loop_back
        if lb is not None and lb.target in agent_refs and reachable_targets:
            loop_back_edges[name] = _LoopBackEdge(
                source=name,
                forward_target=reachable_targets[0],
                target=lb.target,
                max_iterations=lb.max_iterations,
                until_condition=_make_until_predicate(lb.until),
            )

    entry_name = next(
        (name for name in flow.spec.agents if name in agent_refs and name not in reverse_edges),
        next(iter(agent_refs)),
    )

    reachable: set[str] = set()
    frontier = [entry_name]
    while frontier:
        current = frontier.pop(0)
        if current in reachable:
            continue
        reachable.add(current)
        for target in delegation_edges.get(current, []):
            if target not in reachable:
                frontier.append(target)

    return _TopologyInfo(
        topology_index=topology_index,
        delegation_edges=delegation_edges,
        reverse_edges=reverse_edges,
        strategies=strategies,
        entry_name=entry_name,
        reachable=reachable,
        ensemble_configs=ensemble_configs,
        loop_back_edges=loop_back_edges,
    )


def _ensemble_source_for_fan_in(
    topo: _TopologyInfo,
    target: str,
) -> tuple[str, EnsembleConfig] | None:
    """Return the (source, config) when a fan-in target is fed by one ensemble source.

    Voting only replaces concatenation when every reachable source delegating
    to ``target`` is an ensemble target of the same upstream source. Mixed
    fan-ins keep the default concatenating transform.
    """
    incoming = [s for s in topo.reverse_edges.get(target, []) if s in topo.reachable]
    if not incoming:
        return None
    for source_name, ensemble_cfg in topo.ensemble_configs.items():
        ensemble_targets = [
            t for t in topo.delegation_edges.get(source_name, []) if t in topo.reachable
        ]
        if set(incoming) == set(ensemble_targets):
            return source_name, ensemble_cfg
    return None


def _create_graph_nodes(
    builder: GraphBuilder,
    topo: _TopologyInfo,
) -> _GraphNodes:
    """Create step, join, and transform nodes for all reachable agents."""
    steps: dict[str, object] = {}
    for name in topo.reachable:
        idx = topo.topology_index.get(name, 0)
        step_fn = _make_agent_step(name, idx)
        step = builder.step(node_id=NodeID(name))(step_fn)
        steps[name] = step

    # Detect fan-in targets (multiple incoming delegation edges)
    fan_in_targets: set[str] = set()
    for target, sources in topo.reverse_edges.items():
        incoming = [s for s in sources if s in topo.reachable]
        if len(incoming) > 1:
            fan_in_targets.add(target)

    # Create joins for fan-in targets. When every source feeding a fan-in
    # target is an ensemble target of a single upstream source, the join
    # transform votes on the branch outputs instead of concatenating them.
    joins: dict[str, object] = {}
    join_transforms: dict[str, object] = {}
    for target in fan_in_targets:
        join = builder.join(
            reducer=reduce_list_append,
            initial_factory=list,
            node_id=NodeID(f"_join_{target}"),
        )
        joins[target] = join
        ensemble_source = _ensemble_source_for_fan_in(topo, target)
        if ensemble_source is not None:
            source_name, ensemble_cfg = ensemble_source
            transform_fn = _make_ensemble_reducer(
                source_name, topo.delegation_edges[source_name], ensemble_cfg
            )
        else:
            transform_fn = _make_join_transform(target)
        transform = builder.step(node_id=NodeID(f"_transform_{target}"))(transform_fn)
        join_transforms[target] = transform

    # Identify terminal agents (no outgoing delegation)
    terminal_services: set[str] = set()
    for name in topo.reachable:
        targets = topo.delegation_edges.get(name, [])
        if not [t for t in targets if t in topo.reachable]:
            terminal_services.add(name)

    # Identify fan-out sources whose ALL targets are terminal (need a terminal join).
    # "all" concatenates the branch outputs; "ensemble" votes on them instead.
    terminal_joins: dict[str, object] = {}
    terminal_join_transforms: dict[str, object] = {}
    for name in topo.reachable:
        targets = topo.delegation_edges.get(name, [])
        reachable_targets = [t for t in targets if t in topo.reachable]
        strategy = topo.strategies.get(name, "all")
        if (
            len(reachable_targets) > 1
            and strategy in ("all", "ensemble")
            and all(t in terminal_services for t in reachable_targets)
            and not any(t in fan_in_targets for t in reachable_targets)
        ):
            join = builder.join(
                reducer=reduce_list_append,
                initial_factory=list,
                node_id=NodeID(f"_terminal_join_{name}"),
            )
            terminal_joins[name] = join
            ensemble_cfg = topo.ensemble_configs.get(name)
            if ensemble_cfg is not None:
                transform_fn = _make_ensemble_reducer(name, reachable_targets, ensemble_cfg)
            else:
                transform_fn = _make_join_transform(f"terminal_{name}")
            transform = builder.step(node_id=NodeID(f"_terminal_transform_{name}"))(transform_fn)
            terminal_join_transforms[name] = transform

    # Create the decider step for each loop-back source. The decider increments
    # the per-edge iteration counter and tags the envelope ("continue" routes
    # back to the loop target, "exit" routes to the end). The decision node
    # itself is created during wiring, mirroring routing decisions.
    loop_back_deciders: dict[str, object] = {}
    for source_name, lb_edge in topo.loop_back_edges.items():
        decider_fn = _make_loop_back_decider(lb_edge)
        decider = builder.step(node_id=NodeID(f"_loop_decider_{source_name}"))(decider_fn)
        loop_back_deciders[source_name] = decider

    return _GraphNodes(
        steps=steps,
        fan_in_targets=fan_in_targets,
        joins=joins,
        join_transforms=join_transforms,
        terminal_services=terminal_services,
        terminal_joins=terminal_joins,
        terminal_join_transforms=terminal_join_transforms,
        loop_back_deciders=loop_back_deciders,
    )


def _wire_graph_edges(
    builder: GraphBuilder,
    topo: _TopologyInfo,
    nodes: _GraphNodes,
    agent_refs: dict[str, AgentRef],
) -> None:
    """Wire all edges: start, agent outputs, joins, terminals."""
    # Start -> entry
    builder.add(builder.edge_from(builder.start_node).to(nodes.steps[topo.entry_name]))

    # Wire edges for each agent
    for name in topo.reachable:
        targets = topo.delegation_edges.get(name, [])
        reachable_targets = [t for t in targets if t in topo.reachable]

        if not reachable_targets:
            continue  # terminal -- wired below

        strategy = topo.strategies.get(name, "all")

        if len(reachable_targets) == 1:
            target = reachable_targets[0]
            dest = nodes.joins[target] if target in nodes.fan_in_targets else nodes.steps[target]
            builder.add(builder.edge_from(nodes.steps[name]).to(dest))
        elif strategy in ("all", "ensemble"):
            fork_id = ForkID(f"fork_{name}")

            def _make_broadcast(
                targets_=reachable_targets,
                joins_=nodes.joins,
                fan_in_=nodes.fan_in_targets,
                steps_=nodes.steps,
            ):
                def _broadcast(ep):
                    paths = []
                    for t in targets_:
                        dest = joins_[t] if t in fan_in_ else steps_[t]
                        paths.append(ep.to(dest))
                    return paths

                return _broadcast

            builder.add(
                builder.edge_from(nodes.steps[name]).broadcast(_make_broadcast(), fork_id=fork_id)
            )
        else:
            _wire_routing_decision(
                builder, nodes.steps, name, reachable_targets, strategy, agent_refs
            )

    # Wire fan-in join -> transform -> target step
    for target in nodes.fan_in_targets:
        builder.add(builder.edge_from(nodes.joins[target]).to(nodes.join_transforms[target]))
        builder.add(builder.edge_from(nodes.join_transforms[target]).to(nodes.steps[target]))

    # Wire terminal joins -> transform -> end
    for source_name, join in nodes.terminal_joins.items():
        transform = nodes.terminal_join_transforms[source_name]
        builder.add(builder.edge_from(join).to(transform))
        builder.add(builder.edge_from(transform).to(builder.end_node))

    # Wire remaining terminal agents directly to end
    fan_out_terminal_services: set[str] = set()
    for source_name in nodes.terminal_joins:
        targets = topo.delegation_edges.get(source_name, [])
        fan_out_terminal_services.update(t for t in targets if t in topo.reachable)

    # A loop-back forward target (the critic) feeds the loop decider instead of
    # the end node, so exclude it from the direct terminal wiring.
    loop_forward_targets = {lb.forward_target for lb in topo.loop_back_edges.values()}

    for name in nodes.terminal_services:
        if name in loop_forward_targets:
            continue
        if name in fan_out_terminal_services:
            for source_name, join in nodes.terminal_joins.items():
                source_targets = topo.delegation_edges.get(source_name, [])
                if name in source_targets:
                    builder.add(builder.edge_from(nodes.steps[name]).to(join))
                    break
        else:
            builder.add(builder.edge_from(nodes.steps[name]).to(builder.end_node))

    _wire_loop_back_edges(builder, topo, nodes)


def _wire_loop_back_edges(
    builder: GraphBuilder,
    topo: _TopologyInfo,
    nodes: _GraphNodes,
) -> None:
    """Wire bounded loop-back edges: forward_target -> decider -> decision.

    The decision routes ``"continue"`` back to the loop target (closing the
    refine cycle) and ``"exit"`` to the end node once the iteration cap is hit
    or the ``until`` predicate matches.
    """
    for source_name, lb_edge in topo.loop_back_edges.items():
        decider = nodes.loop_back_deciders[source_name]
        decision = builder.decision(node_id=f"_loop_decision_{source_name}")

        # forward target output (the critic) feeds the decider
        builder.add(builder.edge_from(nodes.steps[lb_edge.forward_target]).to(decider))

        target_dest = (
            nodes.joins[lb_edge.target]
            if lb_edge.target in nodes.fan_in_targets
            else nodes.steps[lb_edge.target]
        )
        decision = decision.branch(
            builder.match(tuple, matches=lambda x: x[0] == "continue")
            .transform(lambda ctx: ctx.inputs[1])
            .to(target_dest)
        )
        decision = decision.branch(
            builder.match(tuple, matches=lambda x: x[0] == "exit")
            .transform(lambda ctx: ctx.inputs[1])
            .to(builder.end_node)
        )
        builder.add(builder.edge_from(decider).to(decision))


def build_flow_graph(
    flow: FlowDefinition,
    agent_refs: dict[str, AgentRef],
):
    """Build a pydantic-graph from flow agent topology.

    Returns the built ``Graph`` object ready for ``await graph.run(...)``.
    """
    topo = _compute_topology(flow, agent_refs)
    builder = GraphBuilder(
        name=flow.metadata.name,
        state_type=Blackboard,
        deps_type=FlowGraphDeps,
        input_type=DelegationEnvelope,
        output_type=DelegationEnvelope,
    )
    nodes = _create_graph_nodes(builder, topo)
    _wire_graph_edges(builder, topo, nodes, agent_refs)
    return builder.build(), topo.entry_name


def _wire_routing_decision(builder, steps, source_name, targets, strategy, agent_refs):
    """Wire a Decision node for keyword/sense routing."""
    from initrunner.services.role_selector import RoleCandidate

    candidates = []
    for target_name in targets:
        ref = agent_refs[target_name]
        candidates.append(
            RoleCandidate(
                path=Path("."),
                name=target_name,
                description=ref.role.metadata.description,
                tags=list(ref.role.metadata.tags),
            )
        )

    # Create a routing step that evaluates select_candidate_sync and forwards
    # to the correct target by returning tagged output
    allow_llm = strategy == "sense"

    async def route_step(ctx: StepContext[Blackboard, FlowGraphDeps, DelegationEnvelope]):
        from initrunner.services.role_selector import select_candidate_sync

        envelope = ctx.inputs
        result = await anyio.to_thread.run_sync(  # type: ignore[unresolved-attribute]
            lambda: select_candidate_sync(envelope.prompt, candidates, allow_llm=allow_llm)
        )
        selected = result.candidate.name
        # Return (selected_target, envelope) so decision can route
        return (selected, envelope)

    router = builder.step(node_id=NodeID(f"_route_{source_name}"))(route_step)
    builder.add(builder.edge_from(steps[source_name]).to(router))

    # Decision after router: match on selected target name
    decision = builder.decision(node_id=f"_decision_{source_name}")
    for target_name in targets:
        decision = decision.branch(
            builder.match(
                tuple,
                matches=lambda x, tn=target_name: x[0] == tn,
            )
            .transform(lambda ctx: ctx.inputs[1])
            .to(steps[target_name])
        )
    builder.add(builder.edge_from(router).to(decision))


# ---------------------------------------------------------------------------
# Step factories
# ---------------------------------------------------------------------------


def _empty_envelope(
    envelope: DelegationEnvelope, service_name: str, idx: int
) -> DelegationEnvelope:
    """Build an empty-output envelope for blocked/failed steps."""
    return DelegationEnvelope(
        prompt="",
        trace=(*envelope.trace, service_name),
        original_prompt=envelope.original_prompt,
        source_service=service_name,
        message_history=None,
        one_shot=envelope.one_shot,
        topology_index=idx,
        loop_back_iteration=envelope.loop_back_iteration,
    )


def _output_envelope(
    envelope: DelegationEnvelope,
    service_name: str,
    topology_index: int,
    result: RunResult,
) -> DelegationEnvelope:
    """Build the downstream envelope from a (possibly replayed) result."""
    output = result.output if result.success else ""
    return DelegationEnvelope(
        prompt=output,
        trace=(*envelope.trace, service_name),
        original_prompt=envelope.original_prompt,
        source_service=service_name,
        message_history=None,
        one_shot=envelope.one_shot,
        topology_index=topology_index,
        loop_back_iteration=envelope.loop_back_iteration,
    )


def _make_agent_step(service_name: str, topology_index: int):
    """Create an async step function for a flow agent."""

    async def agent_step(
        ctx: StepContext[Blackboard, FlowGraphDeps, DelegationEnvelope],
    ) -> DelegationEnvelope:
        deps = ctx.deps
        ref = deps.services[service_name]
        envelope = ctx.inputs
        blackboard = ctx.state

        # Callback
        if deps.on_service_start:
            deps.on_service_start(service_name)

        # Checkpoint replay: a successfully recorded delegation is restored
        # from the durable journal instead of re-running the agent. one_shot
        # runs never journal, so they never replay.
        if deps.checkpoint_journal is not None and not envelope.one_shot:
            replayed = deps.checkpoint_journal.get_replay(deps.flow_run_id, service_name)
            if replayed is not None:
                logger.info(
                    "Replaying checkpoint: flow_run_id=%s service=%s",
                    deps.flow_run_id,
                    service_name,
                )
                ref.last_result = replayed.result
                ref.last_messages = replayed.messages
                ref.run_count += 1
                if deps.on_service_complete:
                    deps.on_service_complete(service_name, replayed.result)
                return _output_envelope(envelope, service_name, topology_index, replayed.result)

        # Delegation policy check
        if envelope.source_service is not None:
            from initrunner.agent.delegation import check_delegation_policy

            source_ref = deps.services.get(envelope.source_service)
            source_metadata = source_ref.role.metadata if source_ref else None
            if source_metadata and not check_delegation_policy(
                source_metadata, service_name, ref.role.metadata
            ):
                logger.warning(
                    "Delegation policy denied: %s -> %s",
                    envelope.source_service,
                    service_name,
                )
                if deps.on_service_complete:
                    deps.on_service_complete(service_name, RunResult(run_id="policy-denied"))
                return _empty_envelope(envelope, service_name, topology_index)

        # Depth check
        if len(envelope.trace) > _MAX_DELEGATION_DEPTH:
            logger.warning(
                "Delegation depth exceeded (%d): %s",
                len(envelope.trace),
                " -> ".join(envelope.trace),
            )
            if deps.on_service_complete:
                deps.on_service_complete(service_name, RunResult(run_id="depth-exceeded"))
            return _empty_envelope(envelope, service_name, topology_index)

        # OTel context
        trigger_metadata = {
            "_flow_trace": ",".join((*envelope.trace, service_name)),
            "_flow_original_prompt": envelope.original_prompt,
            "flow_name": deps.flow_name,
            "flow_run_id": deps.flow_run_id,
            "service_name": service_name,
        }
        if envelope.source_service:
            trigger_metadata["_flow_source_output"] = envelope.prompt[:500]

        from initrunner.observability import extract_trace_context

        parent_ctx = extract_trace_context(trigger_metadata)
        otel_context = _try_import_otel_context()
        ctx_token = None
        if parent_ctx is not None and otel_context is not None:
            ctx_token = otel_context.attach(parent_ctx)

        extra_toolsets = _build_blackboard_toolsets(ref.role, blackboard)

        cb_token = None
        if deps.on_tool_event:
            _cb = deps.on_tool_event
            cb_token = set_tool_event_callback(lambda event, _name=service_name: _cb(_name, event))
        try:
            msg_history = envelope.message_history if service_name == deps.entry_service else None
            result, new_messages = await execute_run_async(
                ref.agent,
                ref.role,
                envelope.prompt,
                audit_logger=deps.audit_logger,
                message_history=msg_history,
                trigger_type="delegate" if envelope.source_service else "flow",
                trigger_metadata=trigger_metadata,
                extra_toolsets=extra_toolsets or None,
            )
        finally:
            if cb_token is not None:
                reset_tool_event_callback(cb_token)
            if ctx_token is not None and otel_context is not None:
                otel_context.detach(ctx_token)

        # Update agent ref
        ref.last_result = result
        ref.last_messages = new_messages
        ref.run_count += 1
        if not result.success:
            ref.error_count += 1

        # Record durable checkpoint for resumable flows (never one-shot).
        if deps.checkpoint_journal is not None and not envelope.one_shot:
            deps.checkpoint_journal.record_completion(
                deps.flow_run_id,
                service_name,
                topology_index,
                envelope,
                result,
                new_messages,
            )

        # Prune memory sessions
        if ref.role.spec.memory is not None:
            _prune_memory(ref)

        # Role sinks (daemon mode only)
        if not envelope.one_shot and ref.sink_dispatcher is not None:
            try:
                ref.sink_dispatcher.dispatch(
                    result,
                    envelope.prompt,
                    trigger_type="delegate",
                    trigger_metadata=trigger_metadata,
                )
            except Exception:
                logger.exception("Role sink dispatch failed for %s", service_name)

        # Callback
        if deps.on_service_complete:
            deps.on_service_complete(service_name, result)

        return _output_envelope(envelope, service_name, topology_index, result)

    agent_step.__name__ = f"step_{service_name}"
    agent_step.__qualname__ = f"step_{service_name}"
    return agent_step


def _build_blackboard_toolsets(role: RoleDefinition, blackboard: Blackboard) -> list:
    """Build the blackboard toolset for an agent that declares ``type: blackboard``.

    Returns an empty list when the role has no blackboard tool, so the common
    case adds nothing to the run. The tool is run-scoped, so the standard
    ``build_toolsets`` path skips it; we build it here with the flow's live
    board injected, the same way the autonomous runner injects ReflectionState.
    """
    from initrunner.agent.schema.tools import BlackboardToolConfig
    from initrunner.agent.tools._registry import ToolBuildContext, get_builder

    config = next(
        (t for t in role.spec.tools if isinstance(t, BlackboardToolConfig)),
        None,
    )
    if config is None:
        return []
    builder = get_builder("blackboard")
    if builder is None:
        return []
    ctx = ToolBuildContext(role=role)
    return [builder(config, ctx, blackboard)]


def _make_loop_back_decider(lb_edge: _LoopBackEdge):
    """Create the decider step for a bounded loop-back edge.

    The step increments the per-edge iteration counter on a fresh envelope and
    returns a ``(decision, envelope)`` tuple. ``decision`` is ``"continue"`` to
    loop back to the target, or ``"exit"`` once ``max_iterations`` rounds have
    completed or the ``until`` predicate matches the latest output.
    """

    async def loop_back_decider(
        ctx: StepContext[Blackboard, FlowGraphDeps, DelegationEnvelope],
    ) -> tuple[str, DelegationEnvelope]:
        from dataclasses import replace

        envelope = ctx.inputs
        completed = envelope.loop_back_iteration + 1
        until_met = lb_edge.until_condition is not None and lb_edge.until_condition(envelope)
        should_exit = completed >= lb_edge.max_iterations or until_met

        if should_exit:
            logger.info(
                "Loop-back exit: source=%s target=%s iterations=%d until_met=%s",
                lb_edge.source,
                lb_edge.target,
                completed,
                until_met,
            )
            return ("exit", envelope)

        next_envelope = replace(
            envelope,
            source_service=lb_edge.forward_target,
            loop_back_iteration=completed,
        )
        return ("continue", next_envelope)

    loop_back_decider.__name__ = f"loop_decider_{lb_edge.source}"
    loop_back_decider.__qualname__ = f"loop_decider_{lb_edge.source}"
    return loop_back_decider


# Per-key value preview bound for the structured board section a fan-in join
# folds into its combined output, keeping the merged prompt from ballooning.
_JOIN_BOARD_VALUE_PREVIEW_CHARS = 500


def _make_join_transform(target_name: str):
    """Create a step that merges joined outputs and the shared blackboard.

    Branch outputs are still concatenated for the downstream agent, but the
    join also reads the structured entries posted on the blackboard during the
    fan-out and folds them into a dedicated section. A value an upstream agent
    posted is therefore visible to the join target as named, attributed data
    rather than only as free text buried in a branch's prompt. Entries that
    were claimed upstream are gone from ``entries`` and so do not reappear.
    """

    async def join_transform(
        ctx: StepContext[Blackboard, FlowGraphDeps, list[DelegationEnvelope]],
    ) -> DelegationEnvelope:
        envelopes = ctx.inputs
        sorted_envs = sorted(envelopes, key=lambda e: e.topology_index)
        parts = [e.prompt for e in sorted_envs if e.prompt]

        board = ctx.state
        if board is not None and board.entries:
            board_lines = ["=== Shared blackboard ==="]
            for key, entry in board.entries.items():
                value = entry.value
                if len(value) > _JOIN_BOARD_VALUE_PREVIEW_CHARS:
                    value = value[:_JOIN_BOARD_VALUE_PREVIEW_CHARS] + " [truncated]"
                board_lines.append(f"- {key} (by {entry.author}): {value}")
            parts.append("\n".join(board_lines))

        combined = "\n\n---\n\n".join(parts)
        all_traces: list[str] = []
        for e in sorted_envs:
            all_traces.extend(e.trace)
        one_shot = sorted_envs[0].one_shot if sorted_envs else True
        original = sorted_envs[0].original_prompt if sorted_envs else ""
        return DelegationEnvelope(
            prompt=combined,
            trace=tuple(all_traces),
            original_prompt=original,
            source_service=None,
            message_history=None,
            one_shot=one_shot,
        )

    join_transform.__name__ = f"transform_{target_name}"
    join_transform.__qualname__ = f"transform_{target_name}"
    return join_transform


def _select_majority(
    sorted_envs: list[DelegationEnvelope],
) -> tuple[DelegationEnvelope, dict]:
    """Pick the most frequent answer; ties break on lowest topology index."""
    from collections import Counter

    counts = Counter(e.prompt for e in sorted_envs if e.prompt)
    if not counts:
        return sorted_envs[0], {"mode": "majority", "counts": {}}
    top = max(counts.values())
    winner = next(e for e in sorted_envs if e.prompt and counts[e.prompt] == top)
    return winner, {"mode": "majority", "counts": dict(counts), "winning_count": top}


def _select_weighted(
    sorted_envs: list[DelegationEnvelope],
    weights: dict[str, float],
) -> tuple[DelegationEnvelope, dict]:
    """Pick the answer from the highest-weight source; ties break on index."""
    winner = max(
        sorted_envs,
        key=lambda e: (weights.get(e.source_service or "", 0.0), -e.topology_index),
    )
    return winner, {
        "mode": "weighted",
        "weights": dict(weights),
        "winning_source": winner.source_service,
    }


def _make_ensemble_reducer(
    source_name: str,
    target_names: list[str],
    ensemble_cfg: EnsembleConfig,
):
    """Create a join transform that votes on branch outputs and audits the trace.

    Reuses ``eval/judge.py`` for ``mode == "judge"``; ``majority`` and
    ``weighted`` resolve in-process. The winning envelope carries a
    ``vote_trace`` that is recorded on the signed audit chain.
    """

    async def ensemble_reducer(
        ctx: StepContext[Blackboard, FlowGraphDeps, list[DelegationEnvelope]],
    ) -> DelegationEnvelope:
        deps = ctx.deps
        envelopes = ctx.inputs
        sorted_envs = sorted(envelopes, key=lambda e: e.topology_index)
        candidates = [e for e in sorted_envs if e.prompt]

        if not candidates:
            return DelegationEnvelope(
                prompt="",
                trace=(source_name,),
                original_prompt=sorted_envs[0].original_prompt if sorted_envs else "",
                source_service=None,
                message_history=None,
                one_shot=sorted_envs[0].one_shot if sorted_envs else True,
                vote_trace={"mode": ensemble_cfg.mode, "candidates": 0},
            )

        mode = ensemble_cfg.mode
        if mode == "judge":
            from initrunner.eval.judge import ensemble_judge_vote_sync

            outputs = [e.prompt for e in candidates]
            result = await anyio.to_thread.run_sync(  # type: ignore[unresolved-attribute]
                lambda: ensemble_judge_vote_sync(
                    outputs, ensemble_cfg.judge_criteria, ensemble_cfg.judge_model
                )
            )
            winner = candidates[result.winning_index]
            vote_trace = {
                "mode": "judge",
                "judge_model": ensemble_cfg.judge_model,
                "criteria": result.criteria,
                "votes": {str(k): v for k, v in result.votes.items()},
                "consensus": result.consensus_text,
            }
        elif mode == "weighted":
            winner, vote_trace = _select_weighted(candidates, ensemble_cfg.weights or {})
        else:
            winner, vote_trace = _select_majority(candidates)

        vote_trace["candidates"] = [e.prompt for e in candidates]
        vote_trace["winning_source"] = winner.source_service

        if deps.audit_logger is not None:
            deps.audit_logger.log_ensemble_vote(
                source_service=source_name,
                target_services=list(target_names),
                mode=mode,
                winning_output=winner.prompt,
                vote_trace=vote_trace,
                trace=",".join((*winner.trace,)),
                run_id=deps.flow_run_id,
            )

        all_traces: list[str] = []
        for e in sorted_envs:
            all_traces.extend(e.trace)
        return DelegationEnvelope(
            prompt=winner.prompt,
            trace=tuple(all_traces),
            original_prompt=sorted_envs[0].original_prompt,
            source_service=None,
            message_history=None,
            one_shot=sorted_envs[0].one_shot,
            vote_trace=vote_trace,
        )

    ensemble_reducer.__name__ = f"ensemble_{source_name}"
    ensemble_reducer.__qualname__ = f"ensemble_{source_name}"
    return ensemble_reducer


def _prune_memory(ref: AgentRef) -> None:
    """Prune stale memory sessions for an agent."""
    from initrunner.stores.factory import open_memory_store

    mem_cfg = ref.role.spec.memory
    if mem_cfg is None:
        return
    try:
        with open_memory_store(mem_cfg, ref.role.metadata.name, require_exists=False) as store:
            if store is not None:
                store.prune_sessions(ref.role.metadata.name, mem_cfg.max_sessions)
    except Exception:
        logger.debug("Memory prune failed for %s", ref.name, exc_info=True)


# ---------------------------------------------------------------------------
# One-shot execution
# ---------------------------------------------------------------------------


def build_agent_refs(
    services: dict,
    *,
    one_shot: bool = True,
) -> dict[str, AgentRef]:
    """Convert FlowMember instances to lightweight AgentRef objects."""
    refs: dict[str, AgentRef] = {}
    for name, svc in services.items():
        refs[name] = AgentRef(
            name=name,
            role=svc.role,
            agent=svc.agent,
            sink_dispatcher=svc._sink_dispatcher if not one_shot else None,
        )
    return refs


def sync_refs_back(services: dict, refs: dict[str, AgentRef]) -> None:
    """Copy results from AgentRef back to FlowMember for _collect_results."""
    for name, ref in refs.items():
        if name in services:
            svc = services[name]
            svc._last_result = ref.last_result
            svc._last_messages = ref.last_messages
            with svc._counter_lock:
                svc._run_count += ref.run_count
                svc._error_count += ref.error_count


def _persist_blackboard(
    audit_logger: AuditLogger | None,
    flow_run_id: str,
    flow_name: str,
    blackboard: Blackboard,
) -> None:
    """Record the final blackboard state on the audit chain. Never raises.

    Skips persistence when there is no audit logger or the board never held an
    entry, so an ordinary flow with no blackboard tool writes nothing.
    """
    if audit_logger is None:
        return
    if not blackboard.entries and not blackboard.claimed:
        return
    audit_logger.log_blackboard_state(
        flow_run_id=flow_run_id,
        flow_name=flow_name,
        snapshot=blackboard.snapshot(),
    )


async def run_flow_graph_async(
    flow: FlowDefinition,
    services: dict,
    prompt: str,
    *,
    entry_service: str | None = None,
    message_history: list | None = None,
    timeout_seconds: float = 300,
    audit_logger: AuditLogger | None = None,
    on_service_start: Callable[[str], None] | None = None,
    on_service_complete: Callable[[str, RunResult], None] | None = None,
    one_shot: bool = True,
    flow_run_id: str = "",
    on_tool_event: Callable[[str, ToolEvent], None] | None = None,
    checkpoint_journal: CheckpointJournal | None = None,
) -> tuple[dict[str, AgentRef], str, int, bool]:
    """Run the flow graph asynchronously.

    Returns ``(refs, entry_name, elapsed_ms, timed_out)`` so the caller
    can feed them into ``_collect_results``.
    """
    refs = build_agent_refs(services, one_shot=one_shot)
    graph, entry_name = build_flow_graph(flow, refs)

    if entry_service:
        entry_name = entry_service

    envelope = DelegationEnvelope(
        prompt=prompt,
        trace=(),
        original_prompt=prompt,
        source_service=None,
        message_history=message_history,
        one_shot=one_shot,
    )

    deps = FlowGraphDeps(
        services=refs,
        flow_name=flow.metadata.name,
        audit_logger=audit_logger,
        on_service_start=on_service_start,
        on_service_complete=on_service_complete,
        entry_service=entry_name,
        flow_run_id=flow_run_id,
        on_tool_event=on_tool_event,
        checkpoint_journal=checkpoint_journal,
    )

    blackboard = Blackboard()
    timed_out = False
    t0 = time.monotonic()

    try:
        with anyio.fail_after(timeout_seconds):
            await graph.run(state=blackboard, deps=deps, inputs=envelope)
    except TimeoutError:
        timed_out = True

    elapsed_ms = int((time.monotonic() - t0) * 1000)

    _persist_blackboard(audit_logger, flow_run_id, flow.metadata.name, blackboard)

    # Sync results back to FlowMember objects
    sync_refs_back(services, refs)

    return refs, entry_name, elapsed_ms, timed_out


def run_flow_graph_sync(
    flow: FlowDefinition,
    services: dict,
    prompt: str,
    **kwargs,
) -> tuple[dict[str, AgentRef], str, int, bool]:
    """Synchronous wrapper for ``run_flow_graph_async``."""
    return run_sync(run_flow_graph_async(flow, services, prompt, **kwargs))


# ---------------------------------------------------------------------------
# Daemon execution
# ---------------------------------------------------------------------------


async def _daemon_main(
    flow: FlowDefinition,
    services: dict,
    audit_logger: AuditLogger | None,
    shutdown_event: threading.Event,
    on_tool_event: Callable[[str, ToolEvent], None] | None = None,
) -> None:
    """Main daemon loop: poll ingress queue, spawn graph runs."""
    from initrunner._ids import generate_id

    loop = asyncio.get_running_loop()
    refs = build_agent_refs(services, one_shot=False)
    graph, _ = build_flow_graph(flow, refs)
    ingress: queue.Queue[_RunRequest] = queue.Queue(maxsize=32)

    # A durable daemon journals every triggered run so a crash mid-flow can
    # be resumed on the next trigger for the same flow_run_id.
    checkpoint_journal = None
    if flow.spec.durability.active and audit_logger is not None:
        from initrunner.flow.checkpoint import CheckpointJournal

        checkpoint_journal = CheckpointJournal(audit_logger)

    async def _run_graph(req: _RunRequest) -> None:
        flow_run_id = req.flow_run_id or generate_id()
        envelope = DelegationEnvelope(
            prompt=req.prompt,
            trace=(),
            original_prompt=req.prompt,
            source_service=None,
            message_history=None,
            one_shot=False,
        )
        # Track per-run success so we only prune the durable checkpoint journal
        # when every sub-agent succeeded, mirroring the orchestrator's
        # success-gated prune. A sub-agent returning RunResult.success=False
        # does not raise, so graph.run() returns normally; pruning here would
        # defeat resume-after-failure. The flag is run-local (this closure),
        # never shared across concurrent _run_graph tasks.
        run_succeeded = True

        def _on_complete(_service_name: str, result: RunResult) -> None:
            nonlocal run_succeeded
            if not result.success:
                run_succeeded = False

        deps = FlowGraphDeps(
            services=refs,
            flow_name=flow.metadata.name,
            audit_logger=audit_logger,
            on_service_start=None,
            on_service_complete=_on_complete,
            entry_service=req.entry,
            flow_run_id=flow_run_id,
            on_tool_event=on_tool_event,
            checkpoint_journal=checkpoint_journal,
        )
        blackboard = Blackboard()
        try:
            await graph.run(state=blackboard, deps=deps, inputs=envelope)
            # Prune only on a fully successful run that is not a resume. On a
            # failed run the checkpoints MUST remain so "flow resume" can
            # replay completed services and re-run the failed one.
            if checkpoint_journal is not None and run_succeeded and not req.resume:
                checkpoint_journal.prune(flow_run_id)
        except Exception:
            logger.exception("Graph run failed: %s", req.entry)
        finally:
            _persist_blackboard(audit_logger, flow_run_id, flow.metadata.name, blackboard)

    def on_trigger(entry_name: str, event) -> None:
        """Called from trigger threads -- enqueue with backpressure."""
        try:
            ingress.put(
                _RunRequest(entry=entry_name, prompt=event.prompt),
                block=True,
                timeout=5,
            )
        except queue.Full:
            logger.warning("Ingress full, dropping trigger for %s", entry_name)

    # Start trigger dispatchers
    dispatchers: list[TriggerDispatcher] = []
    for name, svc in services.items():
        if svc.role.spec.triggers:
            from initrunner.triggers.dispatcher import TriggerDispatcher

            d = TriggerDispatcher(svc.role.spec.triggers, partial(on_trigger, name))
            d.start_all()
            dispatchers.append(d)

    # Dispatch loop: poll ingress, spawn graph tasks
    try:
        while not shutdown_event.is_set():
            try:
                req = await loop.run_in_executor(None, lambda: ingress.get(timeout=0.5))
            except queue.Empty:
                continue
            task = asyncio.create_task(_run_graph(req))
            task.add_done_callback(lambda t: t.result() if not t.cancelled() else None)
    finally:
        for d in dispatchers:
            d.stop_all()
        # Sync final counters back
        sync_refs_back(services, refs)


def start_daemon(
    flow: FlowDefinition,
    services: dict,
    audit_logger: AuditLogger | None,
    on_tool_event: Callable[[str, ToolEvent], None] | None = None,
) -> tuple[threading.Event, threading.Thread]:
    """Start daemon in a background thread. Returns (shutdown_event, thread)."""
    shutdown = threading.Event()

    def _run():
        anyio.run(partial(_daemon_main, flow, services, audit_logger, shutdown, on_tool_event))

    thread = threading.Thread(target=_run, daemon=True, name="flow-daemon")
    thread.start()
    return shutdown, thread
