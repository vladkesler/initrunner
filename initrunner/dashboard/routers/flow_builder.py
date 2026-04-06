"""Flow builder routes -- scaffold, validate, and save flow projects."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException  # type: ignore[import-not-found]

from initrunner.dashboard.deps import (
    FlowCache,
    RoleCache,
    _flow_id,
    get_flow_cache,
    get_role_cache,
)
from initrunner.dashboard.routers._agent_options import build_agent_options
from initrunner.dashboard.routers._provider_options import gather_provider_options
from initrunner.dashboard.schemas import (
    FlowBuilderOptionsResponse,
    FlowSaveRequest,
    FlowSaveResponse,
    FlowSeedRequest,
    FlowSeedResponse,
    FlowValidateRequest,
    FlowValidateResponse,
    PatternInfo,
)
from initrunner.dashboard.validation import validate_flow_yaml

_logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/flow-builder", tags=["flow-builder"])


# ---------------------------------------------------------------------------
# Pattern metadata
# ---------------------------------------------------------------------------


def _pattern_infos() -> list[PatternInfo]:
    """Build pattern info list with slot names."""
    return [
        PatternInfo(
            name="chain",
            description="Linear A -> B -> C pipeline",
            fixed_topology=False,
            slot_names=["step-1", "step-2", "step-3"],
            min_agents=2,
            max_agents=10,
        ),
        PatternInfo(
            name="fan-out",
            description="Dispatch to all workers simultaneously",
            fixed_topology=False,
            slot_names=["dispatcher", "worker-1", "worker-2"],
            min_agents=3,
            max_agents=10,
        ),
        PatternInfo(
            name="route",
            description="Route to the best specialist automatically",
            fixed_topology=False,
            slot_names=["intake", "researcher", "responder"],
            min_agents=3,
            max_agents=10,
        ),
    ]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/options")
async def flow_builder_options(
    role_cache: Annotated[RoleCache, Depends(get_role_cache)],
    flow_cache: Annotated[FlowCache, Depends(get_flow_cache)],
) -> FlowBuilderOptionsResponse:
    opts = await gather_provider_options(role_cache._settings)

    return FlowBuilderOptionsResponse(
        patterns=_pattern_infos(),
        agents=build_agent_options(role_cache),
        providers=opts.providers,
        detected_provider=opts.detected_provider,
        detected_model=opts.detected_model,
        save_dirs=opts.save_dirs,
        custom_presets=opts.custom_presets,
        ollama_models=opts.ollama_models,
        ollama_base_url=opts.ollama_base_url,
    )


@router.post("/seed")
async def seed_flow(
    req: FlowSeedRequest,
    role_cache: Annotated[RoleCache, Depends(get_role_cache)],
) -> FlowSeedResponse:
    if req.mode == "starter":
        if not req.starter_slug:
            raise HTTPException(status_code=400, detail="starter_slug is required for mode=starter")
        from initrunner.services.agent_builder import rewrite_model_block as _rewrite_model_block
        from initrunner.services.starters import resolve_starter_path

        path = resolve_starter_path(req.starter_slug)
        if path is None:
            raise HTTPException(status_code=404, detail=f"Starter not found: {req.starter_slug}")

        flow_yaml = path.read_text(encoding="utf-8")

        # Load role YAMLs from the roles/ subdirectory
        roles_dir = path.parent / "roles"
        role_yamls: dict[str, str] = {}
        if roles_dir.is_dir():
            for rp in sorted(roles_dir.glob("*.yaml")):
                raw = rp.read_text(encoding="utf-8")
                raw = _rewrite_model_block(raw, provider=req.provider, name=req.model)
                role_yamls[rp.name] = raw

        issues = validate_flow_yaml(flow_yaml)
        return FlowSeedResponse(
            flow_yaml=flow_yaml,
            role_yamls=role_yamls,
            issues=issues,
            ready=not any(i.severity == "error" for i in issues),
        )

    from initrunner.services.flow import build_flow

    # Resolve agent_id -> path for each slot assignment
    slot_assignments: dict[str, Path | None] = {}
    for sa in req.agents:
        if sa.agent_id is not None:
            dr = role_cache.get(sa.agent_id)
            if dr is None:
                raise HTTPException(
                    status_code=400, detail=f"Agent not found for slot '{sa.slot}': {sa.agent_id}"
                )
            slot_assignments[sa.slot] = dr.path
        else:
            slot_assignments[sa.slot] = None

    try:
        bundle = await asyncio.to_thread(
            build_flow,
            req.name,
            pattern=req.pattern,
            slot_assignments=slot_assignments,
            agent_count=req.agent_count,
            shared_memory=req.shared_memory,
            provider=req.provider,
            model_name=req.model,
            routing_strategy=req.routing_strategy,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Schema-only validation
    issues = validate_flow_yaml(bundle.flow_yaml)

    return FlowSeedResponse(
        flow_yaml=bundle.flow_yaml,
        role_yamls=bundle.role_yamls,
        issues=issues,
        ready=not any(i.severity == "error" for i in issues),
    )


@router.post("/validate")
async def validate_flow(req: FlowValidateRequest) -> FlowValidateResponse:
    """Schema-only validation -- does not check that role files exist on disk."""
    issues = validate_flow_yaml(req.yaml_text)
    return FlowValidateResponse(
        issues=issues,
        ready=not any(i.severity == "error" for i in issues),
    )


@router.post("/save")
async def save_flow(
    req: FlowSaveRequest,
    flow_cache: Annotated[FlowCache, Depends(get_flow_cache)],
) -> FlowSaveResponse:
    project_dir = Path(req.directory) / req.project_name

    if project_dir.exists() and not req.force:
        raise HTTPException(
            status_code=409,
            detail=f"Directory already exists: {project_dir}",
        )

    try:
        result = await asyncio.to_thread(
            _write_and_validate, project_dir, req.flow_yaml, req.role_yamls
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    fid = _flow_id(result["flow_path"])
    flow_cache.refresh_one(fid, result["flow_path"])

    next_steps = [
        f"cd {project_dir}",
        "initrunner flow validate flow.yaml",
        "initrunner flow up flow.yaml",
    ]

    return FlowSaveResponse(
        path=str(result["flow_path"]),
        valid=result["valid"],
        issues=result["issues"],
        next_steps=next_steps,
        flow_id=fid,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_and_validate(project_dir: Path, flow_yaml: str, role_yamls: dict[str, str]) -> dict:
    """Write files to disk and do full validation (flow + role files)."""
    from initrunner.agent.loader import RoleLoadError, load_role
    from initrunner.flow.loader import FlowLoadError, load_flow

    roles_dir = project_dir / "roles"
    roles_dir.mkdir(parents=True, exist_ok=True)

    flow_path = project_dir / "flow.yaml"
    flow_path.write_text(flow_yaml)

    for filename, role_yaml in role_yamls.items():
        (roles_dir / filename).write_text(role_yaml)

    issues: list[str] = []
    valid = True

    try:
        load_flow(flow_path)
    except (FlowLoadError, Exception) as exc:
        issues.append(f"flow.yaml: {exc}")
        valid = False

    for filename in role_yamls:
        role_path = roles_dir / filename
        try:
            load_role(role_path)
        except (RoleLoadError, Exception) as exc:
            issues.append(f"roles/{filename}: {exc}")
            valid = False

    return {
        "flow_path": flow_path,
        "valid": valid,
        "issues": issues,
    }
