"""Compose orchestration service layer."""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from initrunner.audit.logger import AuditLogger
    from initrunner.compose.schema import ComposeDefinition


def load_compose_sync(path: Path) -> ComposeDefinition:
    """Load and validate a compose definition file (sync)."""
    from initrunner.compose.loader import load_compose

    return load_compose(path)


def run_compose_sync(
    compose: ComposeDefinition,
    base_dir: Path,
    *,
    audit_logger: AuditLogger | None = None,
) -> None:
    """Run a compose orchestration (sync, blocking)."""
    from initrunner.compose.orchestrator import run_compose

    run_compose(compose, base_dir, audit_logger=audit_logger)


# ---------------------------------------------------------------------------
# Scaffold helpers
# ---------------------------------------------------------------------------

_ROUTE_SERVICES = 4  # intake + researcher + responder + escalator
_ROUTE_SLOT_NAMES = ["intake", "researcher", "responder", "escalator"]


@dataclasses.dataclass
class ComposeBundle:
    """Pure data: compose YAML + any generated placeholder role YAMLs."""

    compose_yaml: str
    role_yamls: dict[str, str]  # filename -> yaml (placeholders only)


@dataclasses.dataclass
class ScaffoldResult:
    """Result of scaffolding a compose project directory."""

    project_dir: Path
    compose_path: Path
    role_paths: list[Path]


def build_compose(
    name: str,
    *,
    pattern: str = "pipeline",
    slot_assignments: dict[str, Path | None] | None = None,
    service_count: int = 3,
    shared_memory: bool = False,
    provider: str = "openai",
    model_name: str | None = None,
) -> ComposeBundle:
    """Generate compose YAML + placeholder role YAMLs (pure, writes nothing).

    *slot_assignments* maps slot name to an existing role path (or ``None``
    for a generated placeholder).  When a slot has a path, the compose
    service ``role:`` field points to that path and no placeholder YAML is
    emitted.  If *slot_assignments* is ``None`` every slot gets a placeholder
    (backwards-compatible with the CLI).

    Route pattern ignores *service_count* -- it always produces 4 services.
    """
    import yaml

    from initrunner.templates import COMPOSE_PATTERNS

    if pattern not in COMPOSE_PATTERNS:
        raise ValueError(f"Unknown pattern '{pattern}'. Choose from: {', '.join(COMPOSE_PATTERNS)}")

    if pattern == "fan-out" and service_count < 3:
        raise ValueError("fan-out requires at least 3 services (1 dispatcher + 2 workers).")
    if pattern == "pipeline" and service_count < 2:
        raise ValueError("pipeline requires at least 2 services.")

    builders = {
        "pipeline": _build_pipeline,
        "fan-out": _build_fan_out,
        "route": _build_route,
    }
    compose_dict, roles = builders[pattern](
        name=name,
        service_count=service_count,
        slot_assignments=slot_assignments or {},
        provider=provider,
        model_name=model_name,
    )

    if shared_memory:
        compose_dict["spec"]["shared_memory"] = {
            "enabled": True,
            "store_path": ".memory",
            "max_memories": 1000,
        }

    compose_yaml = yaml.dump(
        compose_dict, default_flow_style=False, sort_keys=False, allow_unicode=True
    )
    return ComposeBundle(compose_yaml=compose_yaml, role_yamls=roles)


def scaffold_compose_project(
    name: str,
    *,
    pattern: str = "pipeline",
    services: int = 3,
    shared_memory: bool = False,
    provider: str = "openai",
    model_name: str | None = None,
    output_dir: Path = Path("."),
    force: bool = False,
) -> ScaffoldResult:
    """Scaffold a compose project directory with compose.yaml and role files.

    Returns a ``ScaffoldResult`` with the paths of all created files.

    Raises ``ValueError`` for invalid arguments and ``FileExistsError`` if the
    target directory already exists (unless *force* is True).
    """
    from initrunner.agent.loader import load_role
    from initrunner.compose.loader import load_compose

    project_dir = output_dir / name
    if project_dir.exists() and not force:
        raise FileExistsError(f"Directory already exists: {project_dir}")

    bundle = build_compose(
        name,
        pattern=pattern,
        service_count=services,
        shared_memory=shared_memory,
        provider=provider,
        model_name=model_name,
    )

    # Write files
    roles_dir = project_dir / "roles"
    roles_dir.mkdir(parents=True, exist_ok=True)

    compose_path = project_dir / "compose.yaml"
    compose_path.write_text(bundle.compose_yaml)

    role_paths: list[Path] = []
    for filename, role_yaml in bundle.role_yamls.items():
        p = roles_dir / filename
        p.write_text(role_yaml)
        role_paths.append(p)

    # Validate generated files
    load_compose(compose_path)
    for p in role_paths:
        load_role(p)

    return ScaffoldResult(
        project_dir=project_dir,
        compose_path=compose_path,
        role_paths=role_paths,
    )


def _slot_role_path(
    svc_name: str,
    slot_assignments: dict[str, Path | None],
) -> tuple[str, bool]:
    """Return (role path string, is_existing) for a service slot.

    If the slot has an assigned existing role path, returns the absolute path
    string.  Otherwise returns the default ``roles/<name>.yaml`` relative path.
    """
    assigned = slot_assignments.get(svc_name)
    if assigned is not None:
        return str(assigned.resolve()), True
    return f"roles/{svc_name}.yaml", False


def _make_compose_dict(name: str, description: str, services_dict: dict) -> dict:
    return {
        "apiVersion": "initrunner/v1",
        "kind": "Compose",
        "metadata": {"name": name, "description": description},
        "spec": {"services": services_dict},
    }


def _build_pipeline(
    *,
    name: str,
    service_count: int,
    slot_assignments: dict[str, Path | None],
    provider: str,
    model_name: str | None,
) -> tuple[dict, dict[str, str]]:
    from initrunner.templates import build_role_yaml

    svc_names = [f"step-{i}" for i in range(1, service_count + 1)]
    services_dict: dict[str, dict] = {}
    roles: dict[str, str] = {}

    for idx, svc_name in enumerate(svc_names):
        role_path, is_existing = _slot_role_path(svc_name, slot_assignments)
        svc: dict = {"role": role_path}

        if idx > 0:
            svc["depends_on"] = [svc_names[idx - 1]]
        if idx < len(svc_names) - 1:
            svc["sink"] = {"type": "delegate", "target": svc_names[idx + 1]}

        svc["restart"] = {"condition": "on-failure"}
        services_dict[svc_name] = svc

        if not is_existing:
            if idx == 0:
                position = "first"
            elif idx == len(svc_names) - 1:
                position = "last"
            else:
                position = f"stage {idx + 1}"
            roles[f"{svc_name}.yaml"] = build_role_yaml(
                name=svc_name,
                description=f"Stage {idx + 1} of the {name} pipeline",
                provider=provider,
                model_name=model_name,
                system_prompt=(
                    f"You are the {position} stage in a processing pipeline.\n"
                    "Analyze the input and produce structured output for the next stage."
                ),
            )

    return (
        _make_compose_dict(name, f"A {service_count}-service pipeline.", services_dict),
        roles,
    )


def _build_fan_out(
    *,
    name: str,
    service_count: int,
    slot_assignments: dict[str, Path | None],
    provider: str,
    model_name: str | None,
) -> tuple[dict, dict[str, str]]:
    from initrunner.templates import build_role_yaml

    worker_count = service_count - 1
    worker_names = [f"worker-{i}" for i in range(1, worker_count + 1)]

    disp_path, disp_existing = _slot_role_path("dispatcher", slot_assignments)
    services_dict: dict[str, dict] = {
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
        services_dict[wname] = {
            "role": w_path,
            "depends_on": ["dispatcher"],
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
        _make_compose_dict(
            name,
            f"Fan-out with 1 dispatcher and {worker_count} workers.",
            services_dict,
        ),
        roles,
    )


def _build_route(
    *,
    name: str,
    service_count: int,  # ignored -- fixed topology
    slot_assignments: dict[str, Path | None],
    provider: str,
    model_name: str | None,
) -> tuple[dict, dict[str, str]]:
    from initrunner.templates import build_role_yaml

    specialists = [
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
    ]

    specialist_names = [s[0] for s in specialists]

    intake_path, intake_existing = _slot_role_path("intake", slot_assignments)
    services_dict: dict[str, dict] = {
        "intake": {
            "role": intake_path,
            "sink": {
                "type": "delegate",
                "strategy": "sense",
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
        services_dict[sname] = {
            "role": s_path,
            "depends_on": ["intake"],
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
        _make_compose_dict(
            name,
            "Intake routes to specialists via intent sensing.",
            services_dict,
        ),
        roles,
    )
