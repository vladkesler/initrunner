"""Compose builder routes -- scaffold, validate, and save compose projects."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from initrunner.dashboard.deps import (
    ComposeCache,
    RoleCache,
    _compose_id,
    get_compose_cache,
    get_role_cache,
)
from initrunner.dashboard.routers._agent_options import build_agent_options
from initrunner.dashboard.routers._provider_options import gather_provider_options
from initrunner.dashboard.schemas import (
    ComposeBuilderOptionsResponse,
    ComposeSaveRequest,
    ComposeSaveResponse,
    ComposeSeedRequest,
    ComposeSeedResponse,
    ComposeValidateRequest,
    ComposeValidateResponse,
    PatternInfo,
)
from initrunner.dashboard.validation import validate_compose_yaml

_logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/compose-builder", tags=["compose-builder"])


# ---------------------------------------------------------------------------
# Pattern metadata
# ---------------------------------------------------------------------------


def _pattern_infos() -> list[PatternInfo]:
    """Build pattern info list with slot names."""
    from initrunner.services.compose import _ROUTE_SLOT_NAMES

    return [
        PatternInfo(
            name="pipeline",
            description="Linear A -> B -> C chain",
            fixed_topology=False,
            slot_names=["step-1", "step-2", "step-3"],
            min_services=2,
            max_services=10,
        ),
        PatternInfo(
            name="fan-out",
            description="One dispatcher fans out to multiple workers",
            fixed_topology=False,
            slot_names=["dispatcher", "worker-1", "worker-2"],
            min_services=3,
            max_services=10,
        ),
        PatternInfo(
            name="route",
            description="Intake routes to specialists via intent sensing",
            fixed_topology=True,
            slot_names=list(_ROUTE_SLOT_NAMES),
            min_services=4,
            max_services=None,
        ),
    ]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/options")
async def compose_builder_options(
    role_cache: Annotated[RoleCache, Depends(get_role_cache)],
    compose_cache: Annotated[ComposeCache, Depends(get_compose_cache)],
) -> ComposeBuilderOptionsResponse:
    opts = await gather_provider_options(role_cache._settings)

    return ComposeBuilderOptionsResponse(
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
async def seed_compose(
    req: ComposeSeedRequest,
    role_cache: Annotated[RoleCache, Depends(get_role_cache)],
) -> ComposeSeedResponse:
    from initrunner.services.compose import build_compose

    # Resolve agent_id -> path for each slot assignment
    slot_assignments: dict[str, Path | None] = {}
    for sa in req.services:
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
            build_compose,
            req.name,
            pattern=req.pattern,
            slot_assignments=slot_assignments,
            service_count=req.service_count,
            shared_memory=req.shared_memory,
            provider=req.provider,
            model_name=req.model,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Schema-only validation
    issues = validate_compose_yaml(bundle.compose_yaml)

    return ComposeSeedResponse(
        compose_yaml=bundle.compose_yaml,
        role_yamls=bundle.role_yamls,
        issues=issues,
        ready=not any(i.severity == "error" for i in issues),
    )


@router.post("/validate")
async def validate_compose(req: ComposeValidateRequest) -> ComposeValidateResponse:
    """Schema-only validation -- does not check that role files exist on disk."""
    issues = validate_compose_yaml(req.yaml_text)
    return ComposeValidateResponse(
        issues=issues,
        ready=not any(i.severity == "error" for i in issues),
    )


@router.post("/save")
async def save_compose(
    req: ComposeSaveRequest,
    compose_cache: Annotated[ComposeCache, Depends(get_compose_cache)],
) -> ComposeSaveResponse:
    project_dir = Path(req.directory) / req.project_name

    if project_dir.exists() and not req.force:
        raise HTTPException(
            status_code=409,
            detail=f"Directory already exists: {project_dir}",
        )

    try:
        result = await asyncio.to_thread(
            _write_and_validate, project_dir, req.compose_yaml, req.role_yamls
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    cid = _compose_id(result["compose_path"])
    compose_cache.refresh_one(cid, result["compose_path"])

    next_steps = [
        f"cd {project_dir}",
        "initrunner compose validate compose.yaml",
        "initrunner compose up compose.yaml",
    ]

    return ComposeSaveResponse(
        path=str(result["compose_path"]),
        valid=result["valid"],
        issues=result["issues"],
        next_steps=next_steps,
        compose_id=cid,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_and_validate(project_dir: Path, compose_yaml: str, role_yamls: dict[str, str]) -> dict:
    """Write files to disk and do full validation (compose + role files)."""
    from initrunner.agent.loader import RoleLoadError, load_role
    from initrunner.compose.loader import ComposeLoadError, load_compose

    roles_dir = project_dir / "roles"
    roles_dir.mkdir(parents=True, exist_ok=True)

    compose_path = project_dir / "compose.yaml"
    compose_path.write_text(compose_yaml)

    for filename, role_yaml in role_yamls.items():
        (roles_dir / filename).write_text(role_yaml)

    issues: list[str] = []
    valid = True

    try:
        load_compose(compose_path)
    except (ComposeLoadError, Exception) as exc:
        issues.append(f"compose.yaml: {exc}")
        valid = False

    for filename in role_yamls:
        role_path = roles_dir / filename
        try:
            load_role(role_path)
        except (RoleLoadError, Exception) as exc:
            issues.append(f"roles/{filename}: {exc}")
            valid = False

    return {
        "compose_path": compose_path,
        "valid": valid,
        "issues": issues,
    }
