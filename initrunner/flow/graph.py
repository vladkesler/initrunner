"""Graph-based flow execution using pydantic-graph beta.

Replaces the queue-based BFS execution with a pydantic-graph that
models the flow agent topology directly.  Fork/Join provides
native parallel execution for fan-out patterns.
"""

from __future__ import annotations

import asyncio
import queue
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING

import anyio
from pydantic_graph.beta import GraphBuilder, StepContext
from pydantic_graph.beta.id_types import ForkID, NodeID
from pydantic_graph.beta.join import reduce_list_append

from initrunner._async import run_sync
from initrunner._log import get_logger
from initrunner.agent.executor import RunResult, execute_run_async

if TYPE_CHECKING:
    from pydantic_ai import Agent

    from initrunner.agent.schema.role import RoleDefinition
    from initrunner.audit.logger import AuditLogger
    from initrunner.flow.schema import FlowDefinition
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
class _TopologyInfo:
    """Computed delegation topology (pure data, no builder dependency)."""

    topology_index: dict[str, int]
    delegation_edges: dict[str, list[str]]
    reverse_edges: dict[str, list[str]]
    strategies: dict[str, str]
    entry_name: str
    reachable: set[str]


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


# ---------------------------------------------------------------------------
# Daemon ingress
# ---------------------------------------------------------------------------


@dataclass
class _RunRequest:
    entry: str
    prompt: str
    metadata: dict[str, str] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------


def _compute_topology(
    flow: FlowDefinition,
    agent_refs: dict[str, AgentRef],
) -> _TopologyInfo:
    """Compute delegation topology: edges, strategies, entry point, reachable set."""
    topology_index: dict[str, int] = {name: i for i, name in enumerate(flow.spec.agents)}

    delegation_edges: dict[str, list[str]] = {}
    reverse_edges: dict[str, list[str]] = {}
    strategies: dict[str, str] = {}

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
        for t in reachable_targets:
            reverse_edges.setdefault(t, []).append(name)

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
    )


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

    # Create joins for fan-in targets
    joins: dict[str, object] = {}
    join_transforms: dict[str, object] = {}
    for target in fan_in_targets:
        join = builder.join(
            reducer=reduce_list_append,
            initial_factory=list,
            node_id=NodeID(f"_join_{target}"),
        )
        joins[target] = join
        transform_fn = _make_join_transform(target)
        transform = builder.step(node_id=NodeID(f"_transform_{target}"))(transform_fn)
        join_transforms[target] = transform

    # Identify terminal agents (no outgoing delegation)
    terminal_services: set[str] = set()
    for name in topo.reachable:
        targets = topo.delegation_edges.get(name, [])
        if not [t for t in targets if t in topo.reachable]:
            terminal_services.add(name)

    # Identify fan-out sources whose ALL targets are terminal (need a terminal join)
    terminal_joins: dict[str, object] = {}
    terminal_join_transforms: dict[str, object] = {}
    for name in topo.reachable:
        targets = topo.delegation_edges.get(name, [])
        reachable_targets = [t for t in targets if t in topo.reachable]
        strategy = topo.strategies.get(name, "all")
        if (
            len(reachable_targets) > 1
            and strategy == "all"
            and all(t in terminal_services for t in reachable_targets)
            and not any(t in fan_in_targets for t in reachable_targets)
        ):
            join = builder.join(
                reducer=reduce_list_append,
                initial_factory=list,
                node_id=NodeID(f"_terminal_join_{name}"),
            )
            terminal_joins[name] = join
            transform_fn = _make_join_transform(f"terminal_{name}")
            transform = builder.step(node_id=NodeID(f"_terminal_transform_{name}"))(transform_fn)
            terminal_join_transforms[name] = transform

    return _GraphNodes(
        steps=steps,
        fan_in_targets=fan_in_targets,
        joins=joins,
        join_transforms=join_transforms,
        terminal_services=terminal_services,
        terminal_joins=terminal_joins,
        terminal_join_transforms=terminal_join_transforms,
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
        elif strategy == "all":
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

    for name in nodes.terminal_services:
        if name in fan_out_terminal_services:
            for source_name, join in nodes.terminal_joins.items():
                source_targets = topo.delegation_edges.get(source_name, [])
                if name in source_targets:
                    builder.add(builder.edge_from(nodes.steps[name]).to(join))
                    break
        else:
            builder.add(builder.edge_from(nodes.steps[name]).to(builder.end_node))


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
        state_type=type(None),
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

    async def route_step(ctx: StepContext):
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
    )


def _make_agent_step(service_name: str, topology_index: int):
    """Create an async step function for a flow agent."""

    async def agent_step(
        ctx: StepContext[None, FlowGraphDeps, DelegationEnvelope],
    ) -> DelegationEnvelope:
        deps = ctx.deps
        ref = deps.services[service_name]
        envelope = ctx.inputs

        # Callback
        if deps.on_service_start:
            deps.on_service_start(service_name)

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
            )
        finally:
            if ctx_token is not None and otel_context is not None:
                otel_context.detach(ctx_token)

        # Update agent ref
        ref.last_result = result
        ref.last_messages = new_messages
        ref.run_count += 1
        if not result.success:
            ref.error_count += 1

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

        new_trace = (*envelope.trace, service_name)
        output = result.output if result.success else ""
        return DelegationEnvelope(
            prompt=output,
            trace=new_trace,
            original_prompt=envelope.original_prompt,
            source_service=service_name,
            message_history=None,
            one_shot=envelope.one_shot,
            topology_index=topology_index,
        )

    agent_step.__name__ = f"step_{service_name}"
    agent_step.__qualname__ = f"step_{service_name}"
    return agent_step


def _make_join_transform(target_name: str):
    """Create a step that sorts joined outputs and wraps them in an envelope."""

    async def join_transform(
        ctx: StepContext[None, FlowGraphDeps, list[DelegationEnvelope]],
    ) -> DelegationEnvelope:
        envelopes = ctx.inputs
        sorted_envs = sorted(envelopes, key=lambda e: e.topology_index)
        combined = "\n\n---\n\n".join(e.prompt for e in sorted_envs if e.prompt)
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
    )

    timed_out = False
    t0 = time.monotonic()

    try:
        with anyio.fail_after(timeout_seconds):
            await graph.run(state=None, deps=deps, inputs=envelope)
    except TimeoutError:
        timed_out = True

    elapsed_ms = int((time.monotonic() - t0) * 1000)

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
) -> None:
    """Main daemon loop: poll ingress queue, spawn graph runs."""
    loop = asyncio.get_running_loop()
    refs = build_agent_refs(services, one_shot=False)
    graph, _ = build_flow_graph(flow, refs)
    ingress: queue.Queue[_RunRequest] = queue.Queue(maxsize=32)

    async def _run_graph(req: _RunRequest) -> None:
        envelope = DelegationEnvelope(
            prompt=req.prompt,
            trace=(),
            original_prompt=req.prompt,
            source_service=None,
            message_history=None,
            one_shot=False,
        )
        deps = FlowGraphDeps(
            services=refs,
            flow_name=flow.metadata.name,
            audit_logger=audit_logger,
            on_service_start=None,
            on_service_complete=None,
            entry_service=req.entry,
        )
        try:
            await graph.run(state=None, deps=deps, inputs=envelope)
        except Exception:
            logger.exception("Graph run failed: %s", req.entry)

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
) -> tuple[threading.Event, threading.Thread]:
    """Start daemon in a background thread. Returns (shutdown_event, thread)."""
    shutdown = threading.Event()

    def _run():
        anyio.run(partial(_daemon_main, flow, services, audit_logger, shutdown))

    thread = threading.Thread(target=_run, daemon=True, name="flow-daemon")
    thread.start()
    return shutdown, thread
