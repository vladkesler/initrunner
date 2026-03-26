"""Skill management routes -- browse, detail, create, edit, delete."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query  # type: ignore[import-not-found]

from initrunner.dashboard.deps import (
    RoleCache,
    SkillCache,
    _file_id,
    get_role_cache,
    get_skill_cache,
)
from initrunner.dashboard.schemas import (
    DeleteResponse,
    RequirementStatusResponse,
    SkillAgentRef,
    SkillContentResponse,
    SkillContentSaveRequest,
    SkillContentSaveResponse,
    SkillCreateRequest,
    SkillCreateResponse,
    SkillDeleteBlockedResponse,
    SkillDetail,
    SkillSummary,
    SkillToolSummary,
)

router = APIRouter(prefix="/api/skills", tags=["skills"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _summary_from(skill_id: str, skill) -> SkillSummary:
    """Build a SkillSummary from a DiscoveredSkillFull."""
    fm = skill.frontmatter
    has_tools = bool(fm and fm.tools)
    tool_count = len(fm.tools) if fm and fm.tools else 0
    req_statuses = skill.requirement_statuses or []
    requirements_met = all(r.met for r in req_statuses) if req_statuses else True

    return SkillSummary(
        id=skill_id,
        name=skill.name,
        description=skill.description,
        scope=skill.scope,
        has_tools=has_tools,
        tool_count=tool_count,
        is_directory_form=skill.is_directory_form,
        requirements_met=requirements_met,
        requirement_count=len(req_statuses),
        path=str(skill.path),
        error=skill.error,
    )


def _detail_from(
    skill_id: str,
    skill,
    used_by: list[SkillAgentRef],
) -> SkillDetail:
    """Build a SkillDetail from a DiscoveredSkillFull."""
    fm = skill.frontmatter
    req_statuses = skill.requirement_statuses or []
    requirements_met = all(r.met for r in req_statuses) if req_statuses else True

    tools: list[SkillToolSummary] = []
    if fm and fm.tools:
        for t in fm.tools:
            tools.append(SkillToolSummary(type=t.type, summary=t.summary()))

    requirements: list[RequirementStatusResponse] = []
    for r in req_statuses:
        requirements.append(
            RequirementStatusResponse(name=r.name, kind=r.kind, met=r.met, detail=r.detail)
        )

    prompt = skill.prompt or ""
    prompt_preview = prompt[:500] + "..." if len(prompt) > 500 else prompt

    metadata: dict[str, str] = {}
    if fm:
        if fm.metadata:
            metadata = {k: str(v) for k, v in fm.metadata.items()}

    return SkillDetail(
        id=skill_id,
        name=skill.name,
        description=skill.description,
        scope=skill.scope,
        path=str(skill.path),
        is_directory_form=skill.is_directory_form,
        has_resources=skill.has_resources,
        error=skill.error,
        license=fm.license if fm else "",
        compatibility=fm.compatibility if fm else "",
        metadata=metadata,
        tools=tools,
        requirements=requirements,
        requirements_met=requirements_met,
        prompt=prompt,
        prompt_preview=prompt_preview,
        used_by_agents=used_by,
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("")
async def list_skills(
    cache: Annotated[SkillCache, Depends(get_skill_cache)],
    scope: Annotated[str | None, Query()] = None,
    search: Annotated[str | None, Query()] = None,
) -> list[SkillSummary]:
    skills = cache.all()
    result = []
    for sid, skill in skills.items():
        if scope and skill.scope != scope:
            continue
        if search:
            q = search.lower()
            if q not in skill.name.lower() and q not in skill.description.lower():
                continue
        result.append(_summary_from(sid, skill))
    return result


@router.get("/directories")
async def list_directories(
    cache: Annotated[SkillCache, Depends(get_skill_cache)],
) -> list[str]:
    from initrunner.services.skill_service import get_skill_directories

    # Reuse the settings from cache
    return await asyncio.to_thread(get_skill_directories, cache._settings.get_role_dirs())


@router.post("/refresh")
async def refresh_skills(
    cache: Annotated[SkillCache, Depends(get_skill_cache)],
) -> list[SkillSummary]:
    await asyncio.to_thread(cache.refresh)
    return [_summary_from(sid, s) for sid, s in cache.all().items()]


@router.get("/{skill_id}")
async def get_skill_detail(
    skill_id: str,
    skill_cache: Annotated[SkillCache, Depends(get_skill_cache)],
    role_cache: Annotated[RoleCache, Depends(get_role_cache)],
) -> SkillDetail:
    skill = skill_cache.get(skill_id)
    if skill is None:
        raise HTTPException(404, detail="Skill not found")

    # Cross-reference: which agents use this skill?
    used_by = await asyncio.to_thread(_resolve_used_by, skill, skill_cache, role_cache)

    return _detail_from(skill_id, skill, used_by)


def _resolve_used_by(skill, skill_cache: SkillCache, role_cache: RoleCache) -> list[SkillAgentRef]:
    """Resolve which agents reference this skill via path-based comparison."""
    from initrunner.services.skill_service import resolve_agent_skill_refs

    skill_path = skill.path.resolve()
    used_by: list[SkillAgentRef] = []

    for agent_id, dr in role_cache.all().items():
        if dr.role is None:
            continue
        if not dr.role.spec.skills:
            continue
        resolved_refs = resolve_agent_skill_refs(
            dr.role.spec.skills,
            dr.path.parent,
            None,  # extra_dirs not available here; bare names still resolve via global dirs
        )
        if skill_path in resolved_refs:
            used_by.append(SkillAgentRef(id=agent_id, name=dr.role.metadata.name))

    return used_by


@router.get("/{skill_id}/content")
async def get_skill_content(
    skill_id: str,
    cache: Annotated[SkillCache, Depends(get_skill_cache)],
) -> SkillContentResponse:
    skill = cache.get(skill_id)
    if skill is None:
        raise HTTPException(404, detail="Skill not found")
    content = await asyncio.to_thread(skill.path.read_text)
    return SkillContentResponse(content=content, path=str(skill.path))


@router.put("/{skill_id}/content")
async def save_skill_content(
    skill_id: str,
    body: SkillContentSaveRequest,
    cache: Annotated[SkillCache, Depends(get_skill_cache)],
) -> SkillContentSaveResponse:
    skill = cache.get(skill_id)
    if skill is None:
        raise HTTPException(404, detail="Skill not found")

    from initrunner.services.skill_service import save_skill_content as svc_save

    valid, issues = await asyncio.to_thread(svc_save, skill.path, body.content)

    if valid:
        cache.refresh_one(skill_id, skill.path)

    return SkillContentSaveResponse(
        path=str(skill.path),
        valid=valid,
        issues=issues,
    )


@router.post("")
async def create_skill(
    body: SkillCreateRequest,
    cache: Annotated[SkillCache, Depends(get_skill_cache)],
) -> SkillCreateResponse:
    from initrunner.agent.skills import SkillLoadError
    from initrunner.services.skill_service import create_skill as svc_create

    directory = Path(body.directory)
    try:
        path = await asyncio.to_thread(svc_create, body.name, directory, body.provider)
    except SkillLoadError as exc:
        raise HTTPException(409, detail=str(exc)) from exc

    skill_id = _file_id(path)
    await asyncio.to_thread(cache.refresh)

    return SkillCreateResponse(id=skill_id, path=str(path), name=body.name)


@router.delete("/{skill_id}")
async def delete_skill(
    skill_id: str,
    cache: Annotated[SkillCache, Depends(get_skill_cache)],
) -> DeleteResponse | SkillDeleteBlockedResponse:
    skill = cache.get(skill_id)
    if skill is None:
        raise HTTPException(404, detail="Skill not found")

    from initrunner.services.skill_service import SkillDeleteBlockedError
    from initrunner.services.skill_service import delete_skill as svc_delete

    try:
        await asyncio.to_thread(svc_delete, skill.path)
    except SkillDeleteBlockedError as exc:
        raise HTTPException(
            409,
            detail=SkillDeleteBlockedResponse(
                id=skill_id,
                path=str(skill.path),
                resource_files=exc.resource_files,
                message=str(exc),
            ).model_dump(),
        ) from exc

    cache.evict(skill_id)
    return DeleteResponse(id=skill_id, path=str(skill.path))
