"""Sequential and parallel pipeline executor for team mode.

The primary execution engine is now :mod:`initrunner.team.graph`.  This
module retains the legacy ``run_team`` / ``run_team_parallel`` functions
(used by tests) and re-exports moved symbols under their old names for
backward compatibility.
"""

from __future__ import annotations

import concurrent.futures
import logging
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from initrunner._ids import generate_id
from initrunner.agent.executor import RunResult
from initrunner.team.graph import _log_team_aggregate

# ---------------------------------------------------------------------------
# Re-exports from new modules (public names + legacy underscore aliases)
# ---------------------------------------------------------------------------
from initrunner.team.prompts import (
    build_agent_prompt,
    build_debate_prompt,
    build_parallel_prompt,
    build_synthesis_prompt,
    truncate_handoff,
)
from initrunner.team.results import (
    StepMetadata,
    TeamResult,
    accumulate_result,
)
from initrunner.team.roles import (
    persona_to_role,
    team_report_role,
)
from initrunner.team.runtime import (
    persona_env,
    resolve_team_model,
    setup_team_tracing,
)
from initrunner.team.schema import PersonaConfig, TeamDefinition
from initrunner.team.stores import (
    apply_shared_stores,
    resolve_shared_paths,
    run_pre_ingestion,
)

# Legacy underscore aliases -- external code may import these directly
_truncate_handoff = truncate_handoff
_build_agent_prompt = build_agent_prompt
_build_parallel_prompt = build_parallel_prompt
_build_debate_prompt = build_debate_prompt
_build_synthesis_prompt = build_synthesis_prompt
_persona_to_role = persona_to_role
_team_report_role = team_report_role
_persona_env = persona_env
_resolve_team_model = resolve_team_model
_setup_team_tracing = setup_team_tracing
_resolve_shared_paths = resolve_shared_paths
_run_pre_ingestion = run_pre_ingestion
_apply_shared_stores = apply_shared_stores
_accumulate_result = accumulate_result

_logger = logging.getLogger(__name__)

# Suppress unused-import warnings for re-exports
__all__ = [
    "StepMetadata",
    "TeamResult",
    "accumulate_result",
    "apply_shared_stores",
    "build_agent_prompt",
    "build_debate_prompt",
    "build_parallel_prompt",
    "build_synthesis_prompt",
    "persona_env",
    "persona_to_role",
    "resolve_shared_paths",
    "resolve_team_model",
    "run_pre_ingestion",
    "run_team",
    "run_team_dispatch",
    "run_team_parallel",
    "setup_team_tracing",
    "team_report_role",
    "truncate_handoff",
]


def run_team(
    team: TeamDefinition,
    task: str,
    *,
    team_dir: Path,
    audit_logger: Any | None = None,
    dry_run_model: Any = None,
    on_persona_start: Callable[[str], None] | None = None,
    on_persona_complete: Callable[[str, RunResult], None] | None = None,
) -> TeamResult:
    """Execute all personas sequentially, passing output between them.

    Args:
        dry_run_model: A ``Model``, model name string, or ``None``.
        on_persona_start: Optional callback invoked with the persona name
            at the start of each persona's execution.
        on_persona_complete: Optional callback invoked with the persona name
            and run result after each persona finishes (success or failure).
    """
    from initrunner.agent.executor import execute_run
    from initrunner.agent.loader import _load_dotenv, build_agent

    team_run_id = generate_id()
    result = TeamResult(team_run_id=team_run_id, team_name=team.metadata.name)

    _load_dotenv(team_dir)
    resolve_team_model(team)

    shared_mem_path, shared_doc_path = resolve_shared_paths(team)

    # Pre-ingest shared documents
    if shared_doc_path and team.spec.shared_documents.sources:
        run_pre_ingestion(team, shared_doc_path, team_dir)

    # Initialize tracing
    tracing_provider = setup_team_tracing(team)

    try:
        prior_outputs: list[tuple[str, str]] = []
        wall_start = time.monotonic()

        for persona_name, persona in team.spec.personas.items():
            if on_persona_start is not None:
                on_persona_start(persona_name)

            # Check cumulative token budget
            if team.spec.guardrails.team_token_budget is not None:
                if result.total_tokens >= team.spec.guardrails.team_token_budget:
                    result.success = False
                    result.error = (
                        f"Team token budget exceeded: {result.total_tokens} >= "
                        f"{team.spec.guardrails.team_token_budget}"
                    )
                    _logger.warning("Team budget exceeded before persona '%s'", persona_name)
                    break

            # Check team timeout
            if team.spec.guardrails.team_timeout_seconds is not None:
                elapsed_s = time.monotonic() - wall_start
                if elapsed_s >= team.spec.guardrails.team_timeout_seconds:
                    result.success = False
                    result.error = (
                        f"Team timeout exceeded: {elapsed_s:.0f}s >= "
                        f"{team.spec.guardrails.team_timeout_seconds}s"
                    )
                    _logger.warning("Team timeout exceeded before persona '%s'", persona_name)
                    break

            role = persona_to_role(persona_name, persona, team)
            apply_shared_stores(role, team, shared_mem_path, shared_doc_path)

            with persona_env(persona.environment):
                agent = build_agent(role, role_dir=team_dir)

                prompt = build_agent_prompt(
                    task, persona_name, prior_outputs, team.spec.handoff_max_chars
                )

                trigger_metadata = {
                    "team_name": team.metadata.name,
                    "team_run_id": team_run_id,
                    "agent_name": persona_name,
                }

                run_result, _ = execute_run(
                    agent,
                    role,
                    prompt,
                    audit_logger=audit_logger,
                    model_override=dry_run_model,
                    trigger_type="team",
                    trigger_metadata=trigger_metadata,
                )

            accumulate_result(result, persona_name, run_result)
            if on_persona_complete is not None:
                on_persona_complete(persona_name, run_result)

            if not run_result.success:
                result.success = False
                result.error = f"Persona '{persona_name}' failed: {run_result.error}"
                _logger.error("Persona '%s' failed: %s", persona_name, run_result.error)
                break

            prior_outputs.append((persona_name, run_result.output))

        # Set final output from last successful persona
        if result.agent_results:
            last = result.agent_results[-1]
            if last.success:
                result.final_output = last.output
    finally:
        if tracing_provider is not None:
            from initrunner.observability import shutdown_tracing

            shutdown_tracing()

    _log_team_aggregate(audit_logger, team, task, result)
    return result


def run_team_parallel(
    team: TeamDefinition,
    task: str,
    *,
    team_dir: Path,
    audit_logger: Any | None = None,
    dry_run_model: Any = None,
    on_persona_start: Callable[[str], None] | None = None,
    on_persona_complete: Callable[[str, RunResult], None] | None = None,
) -> TeamResult:
    """Execute all personas in parallel.

    Results are collected in declared persona order. One persona's failure
    does not cancel others. ``handoff_max_chars`` is irrelevant (no handoff).
    """
    from initrunner.agent.executor import execute_run
    from initrunner.agent.loader import _load_dotenv, build_agent

    team_run_id = generate_id()
    result = TeamResult(team_run_id=team_run_id, team_name=team.metadata.name)

    _load_dotenv(team_dir)
    resolve_team_model(team)

    shared_mem_path, shared_doc_path = resolve_shared_paths(team)

    # Pre-ingest shared documents
    if shared_doc_path and team.spec.shared_documents.sources:
        run_pre_ingestion(team, shared_doc_path, team_dir)

    # Initialize tracing
    tracing_provider = setup_team_tracing(team)

    def _run_single(persona_name: str, persona: PersonaConfig) -> RunResult:
        if on_persona_start is not None:
            on_persona_start(persona_name)

        role = persona_to_role(persona_name, persona, team)
        apply_shared_stores(role, team, shared_mem_path, shared_doc_path)

        agent = build_agent(role, role_dir=team_dir)
        prompt = build_parallel_prompt(task, persona_name)

        trigger_metadata = {
            "team_name": team.metadata.name,
            "team_run_id": team_run_id,
            "agent_name": persona_name,
        }

        run_result, _ = execute_run(
            agent,
            role,
            prompt,
            audit_logger=audit_logger,
            model_override=dry_run_model,
            trigger_type="team",
            trigger_metadata=trigger_metadata,
        )
        if on_persona_complete is not None:
            on_persona_complete(persona_name, run_result)
        return run_result

    try:
        futures: dict[str, concurrent.futures.Future[RunResult]] = {}
        max_workers = min(len(team.spec.personas), 8)

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            for persona_name, persona in team.spec.personas.items():
                futures[persona_name] = executor.submit(_run_single, persona_name, persona)

            # Team-wide timeout
            timeout = team.spec.guardrails.team_timeout_seconds
            _done, not_done = concurrent.futures.wait(
                futures.values(),
                timeout=float(timeout) if timeout is not None else None,
            )
            for f in not_done:
                f.cancel()

        # Collect results in declared persona order
        failed_personas: list[str] = []
        output_parts: list[str] = []

        for persona_name in team.spec.personas:
            future = futures[persona_name]
            if future.cancelled() or not future.done():
                failed_personas.append(persona_name)
                result.agent_names.append(persona_name)
                continue

            try:
                run_result = future.result()
            except Exception as exc:
                _logger.error("Persona '%s' raised: %s", persona_name, exc)
                failed_personas.append(persona_name)
                result.agent_names.append(persona_name)
                continue

            accumulate_result(result, persona_name, run_result)

            if not run_result.success:
                failed_personas.append(persona_name)
                _logger.error("Persona '%s' failed: %s", persona_name, run_result.error)
            else:
                output_parts.append(f"## {persona_name}\n\n{run_result.output}")

        if not_done:
            timed_out = [n for n, f in futures.items() if f in not_done]
            failed_personas.extend(n for n in timed_out if n not in failed_personas)
            result.error = f"Team timeout: personas not finished: {', '.join(timed_out)}"
            result.success = False
        elif failed_personas:
            result.error = f"Persona(s) failed: {', '.join(failed_personas)}"
            result.success = False

        # Check token budget after all runs complete
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

        result.final_output = "\n\n".join(output_parts)
    finally:
        if tracing_provider is not None:
            from initrunner.observability import shutdown_tracing

            shutdown_tracing()

    _log_team_aggregate(audit_logger, team, task, result)
    return result


def run_team_dispatch(
    team: TeamDefinition,
    task: str,
    **kwargs: Any,
) -> TeamResult:
    """Dispatch to graph-based team execution."""
    from initrunner.team.graph import run_team_graph_sync

    return run_team_graph_sync(team, task, **kwargs)
