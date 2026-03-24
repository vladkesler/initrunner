"""Team builder routes -- scaffold, validate, and save team YAML files."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from initrunner.dashboard.deps import TeamCache, _team_id, get_team_cache
from initrunner.dashboard.routers._provider_options import (
    gather_provider_options,
    resolve_custom_provider,
)
from initrunner.dashboard.schemas import (
    TeamBuilderOptionsResponse,
    TeamSaveRequest,
    TeamSaveResponse,
    TeamSeedRequest,
    TeamSeedResponse,
    TeamValidateRequest,
    TeamValidateResponse,
    ValidationIssueResponse,
)

_logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/team-builder", tags=["team-builder"])


@router.get("/options")
async def get_options() -> TeamBuilderOptionsResponse:
    from initrunner.dashboard.config import DashboardSettings

    settings = DashboardSettings()
    opts = await gather_provider_options(settings)

    return TeamBuilderOptionsResponse(
        providers=opts.providers,
        detected_provider=opts.detected_provider,
        detected_model=opts.detected_model,
        save_dirs=opts.save_dirs,
        custom_presets=opts.custom_presets,
        ollama_models=opts.ollama_models,
        ollama_base_url=opts.ollama_base_url,
    )


@router.post("/seed")
async def seed_team(body: TeamSeedRequest) -> TeamSeedResponse:
    from initrunner.services.team_builder import build_blank_team_yaml, validate_team_yaml

    # Resolve team-level provider
    runtime_provider, team_base_url, team_api_key_env = resolve_custom_provider(
        body.provider, body.base_url, body.api_key_env
    )

    # Build resolved persona dicts when structured personas are provided
    personas_resolved: list[dict] | None = None
    if body.personas:
        personas_resolved = []
        for p in body.personas:
            entry: dict = {"name": p.name, "role": p.role}
            if p.model:
                prov, burl, akenv = resolve_custom_provider(
                    p.model.provider, p.model.base_url, p.model.api_key_env
                )
                entry["model"] = {
                    "provider": prov,
                    "name": p.model.name,
                    "base_url": burl,
                    "api_key_env": akenv,
                }
            personas_resolved.append(entry)

    yaml_text = await asyncio.to_thread(
        build_blank_team_yaml,
        name=body.name,
        strategy=body.strategy,
        persona_count=body.persona_count,
        provider=runtime_provider,
        model=body.model,
        personas=personas_resolved,
    )

    # Inject team-level base_url/api_key_env into generated YAML
    if team_base_url:
        yaml_text = _inject_team_model_fields(yaml_text, team_base_url, team_api_key_env)

    _, issues = await asyncio.to_thread(validate_team_yaml, yaml_text)
    issue_responses = [
        ValidationIssueResponse(field=i.field, message=i.message, severity=i.severity)
        for i in issues
    ]
    has_errors = any(i.severity == "error" for i in issues)

    persona_count = len(body.personas) if body.personas else body.persona_count
    return TeamSeedResponse(
        yaml_text=yaml_text,
        explanation=f"Blank {body.strategy} team with {persona_count} personas",
        issues=issue_responses,
        ready=not has_errors,
    )


def _inject_team_model_fields(
    yaml_text: str,
    base_url: str | None,
    api_key_env: str | None,
) -> str:
    """Inject base_url/api_key_env into the top-level spec.model block."""
    lines = yaml_text.splitlines(keepends=True)
    result: list[str] = []
    in_model = False
    injected = False
    for line in lines:
        result.append(line)
        stripped = line.rstrip()
        # Detect the spec-level model block (exactly 2-space indent)
        if stripped == "  model:":
            in_model = True
            continue
        if in_model and not injected:
            # Look for the `name:` line inside the model block
            if stripped.startswith("    name:"):
                if base_url:
                    result.append(f"    base_url: {base_url}\n")
                if api_key_env:
                    result.append(f"    api_key_env: {api_key_env}\n")
                injected = True
                in_model = False
    return "".join(result)


@router.post("/validate")
async def validate_team(body: TeamValidateRequest) -> TeamValidateResponse:
    from initrunner.services.team_builder import validate_team_yaml

    _, issues = await asyncio.to_thread(validate_team_yaml, body.yaml_text)
    issue_responses = [
        ValidationIssueResponse(field=i.field, message=i.message, severity=i.severity)
        for i in issues
    ]
    has_errors = any(i.severity == "error" for i in issues)

    return TeamValidateResponse(issues=issue_responses, ready=not has_errors)


@router.post("/save")
async def save_team(
    body: TeamSaveRequest,
    cache: Annotated[TeamCache, Depends(get_team_cache)],
) -> TeamSaveResponse:
    from initrunner.dashboard.config import DashboardSettings
    from initrunner.services.team_builder import (
        build_team_next_steps,
        validate_team_yaml,
    )

    settings = DashboardSettings()
    allowed_dirs = settings.get_role_dirs()

    target_dir = Path(body.directory).resolve()
    in_allowed = any(
        target_dir == d.resolve() or str(target_dir).startswith(str(d.resolve()))
        for d in allowed_dirs
    )
    if not in_allowed:
        raise HTTPException(
            400,
            detail=f"Directory {body.directory} is not within configured role directories",
        )

    team, issues = await asyncio.to_thread(validate_team_yaml, body.yaml_text)
    errors = [i.message for i in issues if i.severity == "error"]

    if errors and not body.force:
        return TeamSaveResponse(
            path="",
            valid=False,
            issues=errors,
            next_steps=[],
            team_id="",
        )

    output_path = target_dir / body.filename
    if output_path.exists() and not body.force:
        raise HTTPException(409, detail=f"File already exists: {output_path}")

    target_dir.mkdir(parents=True, exist_ok=True)
    await asyncio.to_thread(output_path.write_text, body.yaml_text)

    # Refresh cache
    tid = _team_id(output_path)
    cache.refresh_one(tid, output_path)

    next_steps: list[str] = []
    if team is not None:
        next_steps = build_team_next_steps(output_path, team)

    return TeamSaveResponse(
        path=str(output_path),
        valid=not errors,
        issues=errors,
        next_steps=next_steps,
        team_id=tid,
    )
