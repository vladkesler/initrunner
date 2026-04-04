"""Flow orchestration service layer."""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from initrunner.audit.logger import AuditLogger
    from initrunner.flow.orchestrator import FlowRunResult
    from initrunner.flow.schema import FlowDefinition


def load_flow_sync(path: Path) -> FlowDefinition:
    """Load and validate a flow definition file (sync)."""
    from initrunner.flow.loader import load_flow

    return load_flow(path)


def run_flow_sync(
    flow: FlowDefinition,
    base_dir: Path,
    *,
    audit_logger: AuditLogger | None = None,
) -> None:
    """Run a flow orchestration (sync, blocking)."""
    from initrunner.flow.orchestrator import run_flow

    run_flow(flow, base_dir, audit_logger=audit_logger)


def run_flow_once_sync(
    flow: FlowDefinition,
    base_dir: Path,
    prompt: str,
    *,
    message_history: list | None = None,
    audit_logger: AuditLogger | None = None,
    on_agent_start: Callable[[str], None] | None = None,
    on_agent_complete: Callable | None = None,
) -> FlowRunResult:
    """Run a single prompt through a flow graph (sync)."""
    from initrunner.flow.orchestrator import FlowOrchestrator

    orchestrator = FlowOrchestrator(flow, base_dir, audit_logger=audit_logger)
    return orchestrator.run_once(
        prompt,
        message_history=message_history,
        on_service_start=on_agent_start,
        on_service_complete=on_agent_complete,
    )


async def run_flow_once_async(
    flow: FlowDefinition,
    base_dir: Path,
    prompt: str,
    *,
    message_history: list | None = None,
    audit_logger: AuditLogger | None = None,
    on_agent_start: Callable[[str], None] | None = None,
    on_agent_complete: Callable | None = None,
) -> FlowRunResult:
    """Run a single prompt through a flow graph (async).

    Used by dashboard streaming to avoid the thread pool hop.
    """
    from initrunner.flow.orchestrator import FlowOrchestrator

    orchestrator = FlowOrchestrator(flow, base_dir, audit_logger=audit_logger)
    return await orchestrator.run_once_async(
        prompt,
        message_history=message_history,
        on_service_start=on_agent_start,
        on_service_complete=on_agent_complete,
    )


# ---------------------------------------------------------------------------
# Scaffold helpers
# ---------------------------------------------------------------------------

_ROUTE_SPECIALIST_POOL = [
    "researcher",
    "responder",
    "escalator",
    "analyst",
    "summarizer",
    "validator",
    "coordinator",
    "reviewer",
]
"""Semantic specialist names for the route pattern, ordered by priority."""

_ROUTE_SLOT_NAMES = ["intake", "researcher", "responder", "escalator"]
"""Default slot names (kept for backward compatibility with imports)."""


@dataclasses.dataclass
class FlowBundle:
    """Pure data: flow YAML + any generated placeholder role YAMLs."""

    flow_yaml: str
    role_yamls: dict[str, str]  # filename -> yaml (placeholders only)


@dataclasses.dataclass
class ScaffoldResult:
    """Result of scaffolding a flow project directory."""

    project_dir: Path
    flow_path: Path
    role_paths: list[Path]


def build_flow(
    name: str,
    *,
    pattern: str = "chain",
    slot_assignments: dict[str, Path | None] | None = None,
    agent_count: int = 3,
    shared_memory: bool = False,
    provider: str = "openai",
    model_name: str | None = None,
    routing_strategy: str | None = None,
) -> FlowBundle:
    """Generate flow YAML + placeholder role YAMLs (pure, writes nothing).

    *slot_assignments* maps slot name to an existing role path (or ``None``
    for a generated placeholder).  When a slot has a path, the flow
    agent ``role:`` field points to that path and no placeholder YAML is
    emitted.  If *slot_assignments* is ``None`` every slot gets a placeholder
    (backwards-compatible with the CLI).

    *routing_strategy* sets the delegate sink strategy for the route pattern.
    Defaults to ``"sense"`` for route when ``None``.
    """
    import yaml

    from initrunner.templates import COMPOSE_PATTERNS

    if pattern not in COMPOSE_PATTERNS:
        raise ValueError(f"Unknown pattern '{pattern}'. Choose from: {', '.join(COMPOSE_PATTERNS)}")

    if pattern == "fan-out" and agent_count < 3:
        raise ValueError("fan-out requires at least 3 agents (1 dispatcher + 2 workers).")
    if pattern == "chain" and agent_count < 2:
        raise ValueError("chain requires at least 2 agents.")
    if pattern == "route" and agent_count < 3:
        raise ValueError("route requires at least 3 agents (1 intake + 2 specialists).")

    builders: dict[str, Callable[..., tuple[dict, dict[str, str]]]] = {
        "chain": _build_chain,
        "fan-out": _build_fan_out,
        "route": _build_route,
    }

    kwargs: dict[str, object] = dict(
        name=name,
        agent_count=agent_count,
        slot_assignments=slot_assignments or {},
        provider=provider,
        model_name=model_name,
    )
    if pattern == "route":
        kwargs["routing_strategy"] = routing_strategy or "sense"

    flow_dict, roles = builders[pattern](**kwargs)

    if shared_memory:
        flow_dict["spec"]["shared_memory"] = {
            "enabled": True,
            "store_path": ".memory",
            "max_memories": 1000,
        }

    flow_yaml = yaml.dump(flow_dict, default_flow_style=False, sort_keys=False, allow_unicode=True)
    return FlowBundle(flow_yaml=flow_yaml, role_yamls=roles)


def scaffold_flow_project(
    name: str,
    *,
    pattern: str = "chain",
    agents: int = 3,
    shared_memory: bool = False,
    provider: str = "openai",
    model_name: str | None = None,
    output_dir: Path = Path("."),
    force: bool = False,
) -> ScaffoldResult:
    """Scaffold a flow project directory with flow.yaml and role files.

    Returns a ``ScaffoldResult`` with the paths of all created files.

    Raises ``ValueError`` for invalid arguments and ``FileExistsError`` if the
    target directory already exists (unless *force* is True).
    """
    from initrunner.agent.loader import load_role
    from initrunner.flow.loader import load_flow

    project_dir = output_dir / name
    if project_dir.exists() and not force:
        raise FileExistsError(f"Directory already exists: {project_dir}")

    bundle = build_flow(
        name,
        pattern=pattern,
        agent_count=agents,
        shared_memory=shared_memory,
        provider=provider,
        model_name=model_name,
    )

    # Write files
    roles_dir = project_dir / "roles"
    roles_dir.mkdir(parents=True, exist_ok=True)

    flow_path = project_dir / "flow.yaml"
    flow_path.write_text(bundle.flow_yaml)

    role_paths: list[Path] = []
    for filename, role_yaml in bundle.role_yamls.items():
        p = roles_dir / filename
        p.write_text(role_yaml)
        role_paths.append(p)

    # Validate generated files
    load_flow(flow_path)
    for p in role_paths:
        load_role(p)

    return ScaffoldResult(
        project_dir=project_dir,
        flow_path=flow_path,
        role_paths=role_paths,
    )


def _slot_role_path(
    agent_name: str,
    slot_assignments: dict[str, Path | None],
) -> tuple[str, bool]:
    """Return (role path string, is_existing) for an agent slot.

    If the slot has an assigned existing role path, returns the absolute path
    string.  Otherwise returns the default ``roles/<name>.yaml`` relative path.
    """
    assigned = slot_assignments.get(agent_name)
    if assigned is not None:
        return str(assigned.resolve()), True
    return f"roles/{agent_name}.yaml", False


def _make_flow_dict(name: str, description: str, agents_dict: dict) -> dict:
    return {
        "apiVersion": "initrunner/v1",
        "kind": "Flow",
        "metadata": {"name": name, "description": description},
        "spec": {"agents": agents_dict},
    }


def _build_chain(
    *,
    name: str,
    agent_count: int,
    slot_assignments: dict[str, Path | None],
    provider: str,
    model_name: str | None,
) -> tuple[dict, dict[str, str]]:
    from initrunner.templates import build_role_yaml

    agent_names = [f"step-{i}" for i in range(1, agent_count + 1)]
    agents_dict: dict[str, dict] = {}
    roles: dict[str, str] = {}

    for idx, agent_name in enumerate(agent_names):
        role_path, is_existing = _slot_role_path(agent_name, slot_assignments)
        agent: dict = {"role": role_path}

        if idx > 0:
            agent["needs"] = [agent_names[idx - 1]]
        if idx < len(agent_names) - 1:
            agent["sink"] = {"type": "delegate", "target": agent_names[idx + 1]}

        agent["restart"] = {"condition": "on-failure"}
        agents_dict[agent_name] = agent

        if not is_existing:
            if idx == 0:
                position = "first"
            elif idx == len(agent_names) - 1:
                position = "last"
            else:
                position = f"stage {idx + 1}"
            roles[f"{agent_name}.yaml"] = build_role_yaml(
                name=agent_name,
                description=f"Stage {idx + 1} of the {name} chain",
                provider=provider,
                model_name=model_name,
                system_prompt=(
                    f"You are the {position} stage in a processing chain.\n"
                    "Analyze the input and produce structured output for the next stage."
                ),
            )

    return (
        _make_flow_dict(name, f"A {agent_count}-agent chain.", agents_dict),
        roles,
    )


def _build_fan_out(
    *,
    name: str,
    agent_count: int,
    slot_assignments: dict[str, Path | None],
    provider: str,
    model_name: str | None,
) -> tuple[dict, dict[str, str]]:
    from initrunner.templates import build_role_yaml

    worker_count = agent_count - 1
    worker_names = [f"worker-{i}" for i in range(1, worker_count + 1)]

    disp_path, disp_existing = _slot_role_path("dispatcher", slot_assignments)
    agents_dict: dict[str, dict] = {
        "dispatcher": {
            "role": disp_path,
            "sink": {"type": "delegate", "target": worker_names},
            "restart": {"condition": "on-failure"},
        },
    }

    roles: dict[str, str] = {}
    if not disp_existing:
        roles["dispatcher.yaml"] = build_role_yaml(
            name="dispatcher",
            description=f"Dispatches work to {worker_count} workers",
            provider=provider,
            model_name=model_name,
            system_prompt=(
                "You are a dispatcher agent. Analyze incoming requests and produce "
                "a structured summary. Your output is forwarded to all workers."
            ),
        )

    for wname in worker_names:
        w_path, w_existing = _slot_role_path(wname, slot_assignments)
        agents_dict[wname] = {
            "role": w_path,
            "needs": ["dispatcher"],
            "restart": {"condition": "on-failure"},
        }
        if not w_existing:
            roles[f"{wname}.yaml"] = build_role_yaml(
                name=wname,
                description=f"Worker in the {name} fan-out",
                provider=provider,
                model_name=model_name,
                system_prompt=(
                    "You are a worker agent. Process the dispatched work item and produce a result."
                ),
            )

    return (
        _make_flow_dict(
            name,
            f"Fan-out with 1 dispatcher and {worker_count} workers.",
            agents_dict,
        ),
        roles,
    )


_SPECIALIST_TEMPLATES: list[tuple[str, str, list[str], str]] = [
    (
        "researcher",
        "Investigates technical issues and gathers diagnostic information",
        ["research", "analysis", "investigation", "technical", "diagnose"],
        "You are a technical research agent. When you receive a triaged request "
        "that requires investigation, research the issue thoroughly. Produce a "
        "structured report with: root cause analysis, relevant references, and "
        "recommended resolution steps.",
    ),
    (
        "responder",
        "Drafts direct replies to straightforward questions",
        ["response", "reply", "answer", "chat", "help"],
        "You are a response agent. When you receive a triaged request that can "
        "be answered directly, draft a professional, friendly reply. Keep "
        "responses concise and actionable.",
    ),
    (
        "escalator",
        "Escalates urgent or complex issues to human operators",
        ["escalation", "urgent", "human", "complex", "manager"],
        "You are an escalation agent. When you receive a triaged request that "
        "requires human attention, prepare a structured escalation report with: "
        "severity level, impact summary, recommended response team, and "
        "suggested SLA timeline.",
    ),
    (
        "analyst",
        "Analyses data and produces structured insights",
        ["analysis", "data", "metrics", "insight", "report"],
        "You are an analysis agent. Examine the provided data or context and "
        "produce a structured analysis with key findings, trends, and "
        "actionable recommendations.",
    ),
    (
        "summarizer",
        "Condenses long content into concise summaries",
        ["summary", "condense", "brief", "digest", "overview"],
        "You are a summarization agent. Take the provided content and produce "
        "a concise summary that captures the key points, decisions, and "
        "action items.",
    ),
    (
        "validator",
        "Validates outputs for correctness and compliance",
        ["validation", "check", "verify", "compliance", "quality"],
        "You are a validation agent. Review the provided output for "
        "correctness, completeness, and compliance with stated requirements. "
        "Flag any issues with severity ratings.",
    ),
    (
        "coordinator",
        "Coordinates tasks across multiple teams or systems",
        ["coordination", "schedule", "delegate", "workflow", "orchestrate"],
        "You are a coordination agent. Organize and track multi-step workflows, "
        "assign tasks to appropriate teams, and report on progress and blockers.",
    ),
    (
        "reviewer",
        "Reviews work products and provides structured feedback",
        ["review", "feedback", "critique", "improve", "evaluate"],
        "You are a review agent. Examine the provided work product and deliver "
        "structured feedback with strengths, weaknesses, and specific "
        "improvement suggestions.",
    ),
]


def _build_route(
    *,
    name: str,
    agent_count: int,
    slot_assignments: dict[str, Path | None],
    provider: str,
    model_name: str | None,
    routing_strategy: str = "sense",
) -> tuple[dict, dict[str, str]]:
    from initrunner.templates import build_role_yaml

    # Pick specialist templates for the requested count (intake is slot 0)
    specialist_count = agent_count - 1
    specialists = _SPECIALIST_TEMPLATES[:specialist_count]
    specialist_names = [s[0] for s in specialists]

    intake_path, intake_existing = _slot_role_path("intake", slot_assignments)
    agents_dict: dict[str, dict] = {
        "intake": {
            "role": intake_path,
            "sink": {
                "type": "delegate",
                "strategy": routing_strategy,
                "target": specialist_names,
            },
        },
    }

    roles: dict[str, str] = {}
    if not intake_existing:
        roles["intake.yaml"] = build_role_yaml(
            name="intake",
            description="Receives requests and summarizes them for triage",
            provider=provider,
            model_name=model_name,
            tags=["intake", "triage"],
            system_prompt=(
                "You are an intake agent. When you receive a request, produce a "
                "concise summary including: the issue, urgency level, and the type "
                "of action needed (research, direct response, or escalation). "
                "Be factual and brief."
            ),
        )

    for sname, desc, tags, prompt in specialists:
        s_path, s_existing = _slot_role_path(sname, slot_assignments)
        agents_dict[sname] = {
            "role": s_path,
            "needs": ["intake"],
        }
        if not s_existing:
            roles[f"{sname}.yaml"] = build_role_yaml(
                name=sname,
                description=desc,
                provider=provider,
                model_name=model_name,
                tags=tags,
                system_prompt=prompt,
            )

    return (
        _make_flow_dict(
            name,
            "Intake routes to specialists via intent sensing.",
            agents_dict,
        ),
        roles,
    )
