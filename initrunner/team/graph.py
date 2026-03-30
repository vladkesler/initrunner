"""Graph-based team execution using pydantic-graph beta.

Sequential teams become a linear step chain.
Parallel teams become Fork(broadcast) -> [persona steps] -> Join -> End.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import anyio
from pydantic_graph.beta import GraphBuilder, StepContext
from pydantic_graph.beta.id_types import ForkID, NodeID
from pydantic_graph.beta.join import reduce_list_append

from initrunner._ids import generate_id
from initrunner._log import get_logger
from initrunner.agent.executor import RunResult, execute_run_async
from initrunner.team.runner import (
    StepMetadata,
    TeamResult,
    _accumulate_result,
    _apply_shared_stores,
    _build_agent_prompt,
    _build_parallel_prompt,
    _persona_env,
    _persona_to_role,
    _resolve_shared_paths,
    _resolve_team_model,
    _run_pre_ingestion,
    _setup_team_tracing,
)
from initrunner.team.schema import PersonaConfig, TeamDefinition

logger = get_logger("team.graph")


# ---------------------------------------------------------------------------
# Graph types
# ---------------------------------------------------------------------------


@dataclass
class TeamGraphState:
    """Mutable state flowing through the sequential team graph."""

    prior_outputs: list[tuple[str, str]] = field(default_factory=list)
    total_tokens: int = 0
    wall_start: float = 0.0
    team_result: TeamResult | None = None


@dataclass
class TeamGraphDeps:
    """Injected into every team graph step."""

    team: TeamDefinition
    team_dir: Path
    team_run_id: str
    audit_logger: Any | None
    dry_run_model: Any | None
    on_persona_start: Callable[[str], None] | None
    on_persona_complete: Callable[[str, RunResult], None] | None
    shared_mem_path: str | None
    shared_doc_path: str | None
    task: str  # original task prompt


# ---------------------------------------------------------------------------
# Sequential graph
# ---------------------------------------------------------------------------


def _build_sequential_graph(team: TeamDefinition):
    """Build a linear chain graph for sequential team execution."""
    persona_names = list(team.spec.personas.keys())

    builder = GraphBuilder(
        name=f"team-{team.metadata.name}-seq",
        state_type=TeamGraphState,
        deps_type=TeamGraphDeps,
        input_type=str,  # task prompt
        output_type=str,  # final output
    )

    # Create steps for each persona
    steps = []
    for i, persona_name in enumerate(persona_names):
        step_fn = _make_sequential_persona_step(persona_name, i)
        step = builder.step(node_id=NodeID(persona_name))(step_fn)
        steps.append(step)

    # Wire: start -> p1 -> p2 -> ... -> end
    builder.add(builder.edge_from(builder.start_node).to(steps[0]))
    for i in range(len(steps) - 1):
        builder.add(builder.edge_from(steps[i]).to(steps[i + 1]))
    builder.add(builder.edge_from(steps[-1]).to(builder.end_node))

    return builder.build()


def _make_sequential_persona_step(persona_name: str, index: int):
    """Create an async step for a sequential persona."""

    async def persona_step(ctx: StepContext[TeamGraphState, TeamGraphDeps, str]) -> str:
        deps = ctx.deps
        state = ctx.state
        team = deps.team
        persona = team.spec.personas[persona_name]

        # Callback
        if deps.on_persona_start:
            deps.on_persona_start(persona_name)

        # Token budget check
        if team.spec.guardrails.team_token_budget is not None:
            if state.total_tokens >= team.spec.guardrails.team_token_budget:
                logger.warning("Team budget exceeded before persona '%s'", persona_name)
                return ""

        # Timeout check
        if team.spec.guardrails.team_timeout_seconds is not None:
            elapsed = time.monotonic() - state.wall_start
            if elapsed >= team.spec.guardrails.team_timeout_seconds:
                logger.warning("Team timeout exceeded before persona '%s'", persona_name)
                return ""

        # Build role and agent
        role = _persona_to_role(persona_name, persona, team)
        _apply_shared_stores(role, team, deps.shared_mem_path, deps.shared_doc_path)

        # Build prompt with prior outputs
        prompt = _build_agent_prompt(
            deps.task, persona_name, state.prior_outputs, team.spec.handoff_max_chars
        )

        trigger_metadata = {
            "team_name": team.metadata.name,
            "team_run_id": deps.team_run_id,
            "agent_name": persona_name,
        }

        # Execute with persona environment
        from initrunner.agent.loader import build_agent

        with _persona_env(persona.environment):
            agent = build_agent(role, role_dir=deps.team_dir)
            result, _ = await execute_run_async(
                agent,
                role,
                prompt,
                audit_logger=deps.audit_logger,
                model_override=deps.dry_run_model,
                trigger_type="team",
                trigger_metadata=trigger_metadata,
            )

        # Accumulate to team result
        if state.team_result:
            _accumulate_result(state.team_result, persona_name, result)
            state.total_tokens = state.team_result.total_tokens

        # Callback
        if deps.on_persona_complete:
            deps.on_persona_complete(persona_name, result)

        if not result.success:
            if state.team_result:
                state.team_result.success = False
                state.team_result.error = f"Persona '{persona_name}' failed: {result.error}"
            return ""

        state.prior_outputs.append((persona_name, result.output))
        return result.output

    persona_step.__name__ = f"step_{persona_name}"
    persona_step.__qualname__ = f"step_{persona_name}"
    return persona_step


# ---------------------------------------------------------------------------
# Parallel graph
# ---------------------------------------------------------------------------


def _build_parallel_graph(team: TeamDefinition):
    """Build a Fork/Join graph for parallel team execution."""
    persona_names = list(team.spec.personas.keys())

    builder = GraphBuilder(
        name=f"team-{team.metadata.name}-par",
        state_type=TeamGraphState,
        deps_type=TeamGraphDeps,
        input_type=str,
        output_type=list[tuple[int, str, str]],
    )

    # Create steps for each persona (returns indexed tuple for ordering)
    steps = []
    for i, persona_name in enumerate(persona_names):
        step_fn = _make_parallel_persona_step(persona_name, i)
        step = builder.step(node_id=NodeID(persona_name))(step_fn)
        steps.append(step)

    join = builder.join(
        reducer=reduce_list_append,
        initial_factory=list,
        node_id=NodeID("_join_personas"),
    )

    # Wire: start -> fork -> [steps] -> join -> end
    builder.add(
        builder.edge_from(builder.start_node).broadcast(
            lambda ep, s=steps: [ep.to(step) for step in s],
            fork_id=ForkID("parallel_personas"),
        )
    )
    for step in steps:
        builder.add(builder.edge_from(step).to(join))
    builder.add(builder.edge_from(join).to(builder.end_node))

    return builder.build()


def _make_parallel_persona_step(persona_name: str, declared_index: int):
    """Create an async step for a parallel persona."""

    async def persona_step(
        ctx: StepContext[TeamGraphState, TeamGraphDeps, str],
    ) -> tuple[int, str, str]:
        deps = ctx.deps
        team = deps.team
        persona = team.spec.personas[persona_name]

        # Callback
        if deps.on_persona_start:
            deps.on_persona_start(persona_name)

        role = _persona_to_role(persona_name, persona, team)
        _apply_shared_stores(role, team, deps.shared_mem_path, deps.shared_doc_path)

        prompt = _build_parallel_prompt(deps.task, persona_name)

        trigger_metadata = {
            "team_name": team.metadata.name,
            "team_run_id": deps.team_run_id,
            "agent_name": persona_name,
        }

        from initrunner.agent.loader import build_agent

        agent = build_agent(role, role_dir=deps.team_dir)
        result, _ = await execute_run_async(
            agent,
            role,
            prompt,
            audit_logger=deps.audit_logger,
            model_override=deps.dry_run_model,
            trigger_type="team",
            trigger_metadata=trigger_metadata,
        )

        # Callback
        if deps.on_persona_complete:
            deps.on_persona_complete(persona_name, result)

        output = result.output if result.success else ""
        return (declared_index, persona_name, output)

    persona_step.__name__ = f"step_{persona_name}"
    persona_step.__qualname__ = f"step_{persona_name}"
    return persona_step


# ---------------------------------------------------------------------------
# Execution entry points
# ---------------------------------------------------------------------------


async def run_team_graph_async(
    team: TeamDefinition,
    task: str,
    *,
    team_dir: Path,
    audit_logger: Any | None = None,
    dry_run_model: Any | None = None,
    on_persona_start: Callable[[str], None] | None = None,
    on_persona_complete: Callable[[str, RunResult], None] | None = None,
) -> TeamResult:
    """Run a team through a pydantic-graph, returning TeamResult."""
    from initrunner.agent.loader import _load_dotenv

    team_run_id = generate_id()
    result = TeamResult(team_run_id=team_run_id, team_name=team.metadata.name)

    _load_dotenv(team_dir)
    _resolve_team_model(team)

    shared_mem_path, shared_doc_path = _resolve_shared_paths(team)

    # Pre-ingest shared documents
    if shared_doc_path and team.spec.shared_documents.sources:
        await anyio.to_thread.run_sync(lambda: _run_pre_ingestion(team, shared_doc_path, team_dir))

    # Initialize tracing
    tracing_provider = _setup_team_tracing(team)

    try:
        deps = TeamGraphDeps(
            team=team,
            team_dir=team_dir,
            team_run_id=team_run_id,
            audit_logger=audit_logger,
            dry_run_model=dry_run_model,
            on_persona_start=on_persona_start,
            on_persona_complete=on_persona_complete,
            shared_mem_path=shared_mem_path,
            shared_doc_path=shared_doc_path,
            task=task,
        )

        if team.spec.strategy == "parallel":
            graph = _build_parallel_graph(team)
            state = TeamGraphState(wall_start=time.monotonic(), team_result=result)

            timeout = team.spec.guardrails.team_timeout_seconds
            try:
                if timeout:
                    with anyio.fail_after(float(timeout)):
                        graph_output = await graph.run(state=state, deps=deps, inputs=task)
                else:
                    graph_output = await graph.run(state=state, deps=deps, inputs=task)
            except TimeoutError:
                result.success = False
                result.error = "Team timeout exceeded"
                return result

            # Collect parallel results in declared order
            if isinstance(graph_output, list):
                sorted_outputs = sorted(graph_output, key=lambda t: t[0])
                output_parts = []
                for _idx, pname, output in sorted_outputs:
                    if output:
                        output_parts.append(f"## {pname}\n\n{output}")
                result.final_output = "\n\n".join(output_parts)

            # Accumulate results from parallel runs
            # (parallel steps don't accumulate via state.team_result directly)
            # Re-collect from graph output
            _collect_parallel_results(result, team, graph_output)

            # Post-run token budget check
            if (
                result.success
                and team.spec.guardrails.team_token_budget is not None
                and result.total_tokens > team.spec.guardrails.team_token_budget
            ):
                result.success = False
                result.error = (
                    f"Team token budget exceeded: {result.total_tokens} > "
                    f"{team.spec.guardrails.team_token_budget}"
                )

        elif team.spec.strategy == "debate":
            timeout = team.spec.guardrails.team_timeout_seconds
            try:
                if timeout:
                    with anyio.fail_after(float(timeout)):
                        await _run_debate_async(team, task, deps, result)
                else:
                    await _run_debate_async(team, task, deps, result)
            except TimeoutError:
                result.success = False
                result.error = "Team timeout exceeded"

        else:
            # Sequential
            graph = _build_sequential_graph(team)
            state = TeamGraphState(wall_start=time.monotonic(), team_result=result)

            timeout = team.spec.guardrails.team_timeout_seconds
            try:
                if timeout:
                    with anyio.fail_after(float(timeout)):
                        await graph.run(state=state, deps=deps, inputs=task)
                else:
                    await graph.run(state=state, deps=deps, inputs=task)
            except TimeoutError:
                result.success = False
                result.error = "Team timeout exceeded"

            # Final output from last successful persona
            if result.agent_results:
                last = result.agent_results[-1]
                if last.success:
                    result.final_output = last.output

    finally:
        if tracing_provider is not None:
            from initrunner.observability import shutdown_tracing

            shutdown_tracing()

    return result


# ---------------------------------------------------------------------------
# Debate execution
# ---------------------------------------------------------------------------


async def _run_debate_async(
    team: TeamDefinition,
    task: str,
    deps: TeamGraphDeps,
    result: TeamResult,
) -> None:
    """Run multi-round debate with asyncio.gather per round."""
    import asyncio

    max_rounds = team.spec.debate.max_rounds
    positions: list[tuple[str, str]] = []
    last_complete_round: list[tuple[str, str]] = []

    for round_num in range(1, max_rounds + 1):
        # Check token budget before each round
        if team.spec.guardrails.team_token_budget is not None:
            if result.total_tokens >= team.spec.guardrails.team_token_budget:
                result.success = False
                result.error = (
                    f"Team token budget exceeded: {result.total_tokens} >= "
                    f"{team.spec.guardrails.team_token_budget}"
                )
                break

        # Run all personas concurrently for this round
        coros = [
            _run_debate_persona(
                name,
                persona,
                team,
                task,
                positions,
                round_num,
                max_rounds,
                deps,
                result,
            )
            for name, persona in team.spec.personas.items()
        ]
        round_results = await asyncio.gather(*coros)

        # Check for failures
        round_failed = any(output == "" for _name, output in round_results)
        if round_failed:
            result.success = False
            failed_names = [n for n, o in round_results if o == ""]
            result.error = f"Debate round {round_num}: persona(s) failed: {', '.join(failed_names)}"
            # final_output from last fully completed round
            result.final_output = _format_debate_positions(last_complete_round)
            return

        last_complete_round = list(round_results)
        positions = list(round_results)

    # All rounds succeeded
    if team.spec.debate.synthesize:
        synth_output = await _run_synthesis(team, task, positions, deps, result)
        result.final_output = synth_output
    else:
        result.final_output = _format_debate_positions(positions)


async def _run_debate_persona(
    persona_name: str,
    persona: PersonaConfig,
    team: TeamDefinition,
    task: str,
    prior_positions: list[tuple[str, str]],
    round_num: int,
    max_rounds: int,
    deps: TeamGraphDeps,
    result: TeamResult,
) -> tuple[str, str]:
    """Execute one persona for one debate round. Returns (name, output)."""
    from initrunner.team.runner import (
        _apply_shared_stores,
        _build_debate_prompt,
        _persona_to_role,
    )

    display_name = f"{persona_name} (round {round_num})"

    if deps.on_persona_start:
        deps.on_persona_start(display_name)

    role = _persona_to_role(persona_name, persona, team)
    _apply_shared_stores(role, team, deps.shared_mem_path, deps.shared_doc_path)

    prompt = _build_debate_prompt(
        task,
        persona_name,
        round_num,
        max_rounds,
        prior_positions,
        team.spec.handoff_max_chars,
    )

    trigger_metadata = {
        "team_name": team.metadata.name,
        "team_run_id": deps.team_run_id,
        "agent_name": persona_name,
        "debate_round": str(round_num),
    }

    from initrunner.agent.loader import build_agent

    agent = build_agent(role, role_dir=deps.team_dir)
    run_result, _ = await execute_run_async(
        agent,
        role,
        prompt,
        audit_logger=deps.audit_logger,
        model_override=deps.dry_run_model,
        trigger_type="team",
        trigger_metadata=trigger_metadata,
    )

    _accumulate_result(
        result,
        display_name,
        run_result,
        metadata=StepMetadata(step_kind="persona", round_num=round_num, max_rounds=max_rounds),
    )

    if deps.on_persona_complete:
        deps.on_persona_complete(display_name, run_result)

    if not run_result.success:
        return (persona_name, "")
    return (persona_name, run_result.output)


async def _run_synthesis(
    team: TeamDefinition,
    task: str,
    positions: list[tuple[str, str]],
    deps: TeamGraphDeps,
    result: TeamResult,
) -> str:
    """Run the final synthesis step."""
    from initrunner.agent.schema.base import Kind, RoleMetadata
    from initrunner.agent.schema.role import AgentSpec, RoleDefinition
    from initrunner.team.runner import _build_synthesis_prompt

    if deps.on_persona_start:
        deps.on_persona_start("synthesis")

    # Build a minimal synthesis role using the team model
    spec = AgentSpec(
        role=(
            "You are a synthesis agent. Your job is to produce a unified, "
            "balanced answer from multiple debate positions."
        ),
        model=team.spec.model,
        tools=[],
    )
    role = RoleDefinition(
        apiVersion=team.apiVersion,
        kind=Kind.AGENT,
        metadata=RoleMetadata(name="synthesis"),
        spec=spec,
    )

    prompt = _build_synthesis_prompt(
        task,
        positions,
        team.spec.debate.max_rounds,
    )

    trigger_metadata = {
        "team_name": team.metadata.name,
        "team_run_id": deps.team_run_id,
        "agent_name": "synthesis",
    }

    from initrunner.agent.loader import build_agent

    agent = build_agent(role, role_dir=deps.team_dir)
    run_result, _ = await execute_run_async(
        agent,
        role,
        prompt,
        audit_logger=deps.audit_logger,
        model_override=deps.dry_run_model,
        trigger_type="team",
        trigger_metadata=trigger_metadata,
    )

    _accumulate_result(
        result,
        "synthesis",
        run_result,
        metadata=StepMetadata(
            step_kind="synthesis", round_num=None, max_rounds=team.spec.debate.max_rounds
        ),
    )

    if deps.on_persona_complete:
        deps.on_persona_complete("synthesis", run_result)

    return run_result.output if run_result.success else ""


def _format_debate_positions(positions: list[tuple[str, str]]) -> str:
    """Format debate positions for final output."""
    if not positions:
        return ""
    return "\n\n".join(f"## {name}\n\n{output}" for name, output in positions if output)


def _collect_parallel_results(
    result: TeamResult,
    team: TeamDefinition,
    graph_output: list[tuple[int, str, str]] | None,
) -> None:
    """Collect results from parallel graph output into TeamResult.

    Note: parallel steps run execute_run_async but don't accumulate
    via state.team_result (concurrent mutation isn't safe).  We need
    the graph step to return enough info to build the result.
    For now, the on_persona_complete callback is the accumulation path.
    """
    # Results are already accumulated via on_persona_complete callbacks
    # and _accumulate_result in the step functions (which is not thread-safe
    # for parallel).  For the parallel path, we track failures.
    if graph_output is None:
        return
    for _idx, pname, output in graph_output:
        if not output:
            result.success = False
            if not result.error:
                result.error = f"Persona '{pname}' failed or produced no output"


def run_team_graph_sync(
    team: TeamDefinition,
    task: str,
    **kwargs: Any,
) -> TeamResult:
    """Synchronous wrapper for ``run_team_graph_async``."""

    async def _run():
        return await run_team_graph_async(team, task, **kwargs)

    return anyio.run(_run)
